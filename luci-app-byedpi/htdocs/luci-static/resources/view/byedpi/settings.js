'use strict';
'require view';
'require form';
'require uci';
'require ui';
'require dom';
'require byedpi';

return view.extend({
	load: function() {
		return uci.load('byedpi');
	},

	openEditor: function() {
		if (this.dirty) {
			ui.addNotification(null, E('p', {}, _('Save or reset the form before opening the file editor.')), 'warning');
			return Promise.resolve();
		}

		return uci.changes().then(changes => {
			if (changes.byedpi && changes.byedpi.length) {
				throw new Error(_('Apply or revert pending ByeDPI changes before opening the file editor.'));
			}

			return byedpi.read();
		}).then(data => {
			const editorInput = E('textarea', {
				'rows': 24,
				'spellcheck': 'false',
				'style': 'font-family:monospace;width:100%;box-sizing:border-box;tab-size:4'
			});
			editorInput.value = data.content;

			const errorMessage = E('p', { 'role': 'alert', 'style': 'white-space:pre-wrap' });
			const cancelButton = E('button', { 'class': 'cbi-button', 'click': ui.hideModal }, _('Cancel'));

			const saveButton = E('button', {
				'class': 'cbi-button cbi-button-positive',
				'click': () => {
					saveButton.disabled = cancelButton.disabled = editorInput.disabled = true;
					errorMessage.textContent = '';
					return byedpi.write(editorInput.value, data.revision).then(() => {
						uci.unload('byedpi');
						return uci.load('byedpi');
					}).then(() => {
						if (!this.formHost) {
							ui.hideModal();
							window.location.reload();
							return null;
						}
						return this.map.render();
					}).then(node => {
						if (!node) {
							return;
						}
						// Map.render() updates the attached root in place. Reinserting
						// it with dom.content() would discard its widget registry.
						this.dirty = false;
						this.updateMode();
						ui.hideModal();
						ui.addNotification(null, E('p', {}, _('Configuration saved. Restart ByeDPI on the Service tab to use the new configuration.')), 'info');
					}).catch(error => {
						errorMessage.textContent = error.message;
					}).finally(() => {
						saveButton.disabled = cancelButton.disabled = editorInput.disabled = false;
					});
				}
			}, _('Save'));

			ui.showModal(_('Edit configuration file'), [
				E('p', {}, '/etc/config/byedpi'), editorInput, errorMessage,
				E('div', { 'class': 'right' }, [ cancelButton, ' ', saveButton ])
			]);
		}).catch(error => ui.addNotification(null, E('p', {}, error.message), 'error'));
	},

	render: function() {
		const settingsMap = this.map = new form.Map('byedpi', _('ByeDPI Settings'));
		// Do not silently recreate a missing main section over hand-written configs.
		if (uci.get('byedpi', 'main', '.type') !== 'byedpi') {
			this.handleSave = this.handleSaveApply = this.handleReset = null;
			return E('div', {}, [ E('p', {}, _('The byedpi main section is missing. Use the file editor to add: config byedpi \'main\'.')),
				E('button', { 'class': 'cbi-button cbi-button-action', 'disabled': !L.hasViewPermission() || null, 'click': () => this.openEditor() }, _('Edit configuration file')) ]);
		}

		const mainSection = settingsMap.section(form.NamedSection, 'main', 'byedpi');
		mainSection.addremove = false;

		const enabledField = mainSection.option(form.Flag, 'enabled', _('Enable this configuration'));
		enabledField.rmempty = false;

		const customOptionsField = mainSection.option(form.TextValue, 'cmd_opts', _('Custom command-line options'),
			_('Arguments passed directly to ciadpi. When set, individual settings are ignored for all instances. Shell quoting is not interpreted by the init script.'));
		customOptionsField.rows = 5;
		customOptionsField.wrap = 'soft';
		customOptionsField.write = function(section, value) {
			// Preserve one-line strings byte for byte; only entered line breaks become spaces.
			uci.set('byedpi', section, 'cmd_opts', value.replace(/\r\n|\r|\n/g, ' '));
		};

		const customOptionsWarning = E('p', { 'class': 'alert-message warning', 'hidden': true },
			_('Custom command-line options are active. Individual settings below are ignored.'));

		const warningField = mainSection.option(form.DummyValue, '_custom_warning');
		warningField.renderWidget = () => customOptionsWarning;

		let isAdvancedGroup = false;

		const addIndividualOption = (section, type, name, title, datatype) => {
			const isAdvancedOption = isAdvancedGroup;
			const option = section.option(type, name, title);
			if (datatype) {
				option.datatype = datatype;
			}

			const parseOriginalOption = option.parse;
			option.parse = function(sectionId) {
				if (customOptionsField.formvalue('main')) {
					return Promise.resolve();
				}

				return parseOriginalOption.call(this, sectionId);
			};

			const renderOriginalOption = option.render;
			option.render = function() {
				return Promise.resolve(renderOriginalOption.apply(this, arguments)).then(node =>
					E('fieldset', { 'data-byedpi-individual': '', 'style': 'border:0;padding:0;margin:0;min-width:0',
						'data-byedpi-advanced': isAdvancedOption ? '' : null,
						'disabled': customOptionsField.formvalue('main') || uci.get('byedpi', 'main', 'cmd_opts') ? true : null }, [ node ]));
			};
			return option;
		};

		addIndividualOption(mainSection, form.Value, 'ip', _('Listen address'), 'ipaddr');
		addIndividualOption(mainSection, form.Value, 'port', _('Listen port'), 'port');
		addIndividualOption(mainSection, form.Flag, 'transparent', _('Transparent proxy'));
		addIndividualOption(mainSection, form.Value, 'max_conn', _('Maximum connections'), 'range(1,32766)');
		addIndividualOption(mainSection, form.Flag, 'no_domain', _('Disable domain names'));
		addIndividualOption(mainSection, form.Flag, 'no_udp', _('Disable UDP'));
		addIndividualOption(mainSection, form.Value, 'conn_ip', _('Outgoing address'), 'ipaddr');
		addIndividualOption(mainSection, form.Value, 'buf_size', _('Buffer size'), 'range(1,536870911)');

		const debugField = addIndividualOption(mainSection, form.Flag, 'debug', _('Debug'));
		// debug is numeric upstream. Preserve existing levels until the checkbox changes.
		debugField.cfgvalue = sectionId => +uci.get('byedpi', sectionId, 'debug') > 0 ? '1' : '0';
		debugField.write = (sectionId, value) => {
			const currentDebugState = +uci.get('byedpi', sectionId, 'debug') > 0 ? '1' : '0';
			if (value !== currentDebugState) {
				uci.set('byedpi', sectionId, 'debug', value);
			}
		};
		debugField.rmempty = false;

		isAdvancedGroup = true;

		const renderSection = mainSection.render;
		mainSection.render = function() {
			return Promise.resolve(renderSection.apply(this, arguments)).then(node => {
				const details = E('details', { 'style': 'margin:1em 0' }, [
					E('summary', { 'style': 'cursor:pointer' }, _('Advanced Settings')) ]);
				node.querySelectorAll('[data-byedpi-advanced]').forEach(field => details.appendChild(field));
				const container = node.querySelector('.cbi-section-node') || node;
				container.appendChild(details);
				return node;
			});
		};

		addIndividualOption(mainSection, form.Value, 'pidfile', _('PID file'));
		addIndividualOption(mainSection, form.Value, 'def_ttl', _('Default TTL'), 'range(1,255)');
		addIndividualOption(mainSection, form.Flag, 'tfo', _('TCP Fast Open'));
		addIndividualOption(mainSection, form.Value, 'auto', _('Automatic mode triggers'));
		addIndividualOption(mainSection, form.Value, 'auto_mode', _('Automatic mode'));
		addIndividualOption(mainSection, form.Value, 'cache_ttl', _('Cache TTL'), 'and(uinteger,min(1))');
		addIndividualOption(mainSection, form.Value, 'timeout', _('Timeout'));
		addIndividualOption(mainSection, form.Value, 'proto', _('Protocols'));
		addIndividualOption(mainSection, form.Value, 'hosts', _('Hosts'));
		addIndividualOption(mainSection, form.Value, 'ipset', _('IP set'));
		addIndividualOption(mainSection, form.Value, 'pf', _('Port filter'));
		addIndividualOption(mainSection, form.Value, 'round', _('Round filter'));
		addIndividualOption(mainSection, form.DynamicList, 'split', _('Split positions'));
		addIndividualOption(mainSection, form.Value, 'disorder', _('Disorder position'));
		addIndividualOption(mainSection, form.Value, 'oob', _('Out-of-band position'));
		addIndividualOption(mainSection, form.Value, 'disoob', _('Disordered out-of-band position'));
		addIndividualOption(mainSection, form.Value, 'fake', _('Fake packet position'));
		addIndividualOption(mainSection, form.Flag, 'md5sig', _('TCP MD5 signature'));
		addIndividualOption(mainSection, form.DynamicList, 'fake_sni', _('Fake SNI names'));
		addIndividualOption(mainSection, form.Value, 'ttl', _('Fake packet TTL'), 'range(1,255)');
		addIndividualOption(mainSection, form.Value, 'fake_offset', _('Fake packet offset'));
		addIndividualOption(mainSection, form.Value, 'fake_data', _('Fake data'));
		addIndividualOption(mainSection, form.Value, 'fake_tls_mod', _('Fake TLS modifications'));
		addIndividualOption(mainSection, form.Value, 'oob_data', _('Out-of-band data'));
		addIndividualOption(mainSection, form.Value, 'mod_http', _('HTTP modifications'));
		addIndividualOption(mainSection, form.DynamicList, 'tlsrec', _('TLS record split positions'));
		addIndividualOption(mainSection, form.Value, 'udp_fake', _('Fake UDP packets'), 'uinteger');
		addIndividualOption(mainSection, form.Flag, 'drop_sack', _('Drop SACK'));

		const formContainer = this.formHost = E('div');
		this.updateMode = () => {
			const customOptionsActive = !!customOptionsField.formvalue('main');
			customOptionsWarning.hidden = !customOptionsActive;
			formContainer.querySelectorAll('[data-byedpi-individual]').forEach(fieldset => {
				fieldset.disabled = customOptionsActive || !!settingsMap.readonly;
			});
		};

		const handleFormChange = () => {
			this.dirty = true;
			this.updateMode();
		};

		for (const eventName of [ 'input', 'change', 'widget-change' ]) {
			formContainer.addEventListener(eventName, handleFormChange);
		}

		return settingsMap.render().then(node => {
			dom.content(formContainer, node);
			this.updateMode();

			const editConfigurationButton = E('button', {
				'class': 'cbi-button cbi-button-action',
				'disabled': settingsMap.readonly || null,
				'click': () => this.openEditor()
			}, _('Edit configuration file'));

			return E('div', {}, [
				formContainer,
				E('p', {}, [ editConfigurationButton ])
			]);
		});
	},

	handleSave: function() {
		return this.map.save().then(() => {
			this.dirty = false;
			this.updateMode();
		});
	},
	handleSaveApply: function(ev, mode) {
		return this.handleSave(ev).then(() => ui.changes.apply(mode === '0'));
	},
	handleReset: function() {
		return this.map.reset().then(() => {
			this.dirty = false;
			this.updateMode();
		});
	}
});

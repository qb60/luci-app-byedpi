'use strict';
'require view';
'require poll';
'require byedpi';

return view.extend({
	handleSave: null,
	handleSaveApply: null,
	handleReset: null,

	render: function() {
		const canWrite = L.hasViewPermission();
		const statusFields = {};
		const actionButtons = [];

		const operationMessage = E('p', {
			'role': 'status',
			'style': 'white-space:pre-wrap'
		});

		let operationInProgress = false;
		let statusLoaded = false;

		const updateControls = () => {
			const disabled = operationInProgress || !canWrite || !statusLoaded;

			actionButtons.forEach(button => { button.disabled = disabled; });
		};

		const refreshStatus = () => byedpi.status().then(response => {
			const serviceInfo = byedpi.serviceInfo(response);

			statusFields.version.textContent = response.version || _('Unknown');
			statusFields.status.textContent = serviceInfo.running ? _('Running') : _('Stopped');
			statusFields.autostart.textContent = response.autostart ? _('Enabled') : _('Disabled');
			statusFields.ip.textContent = serviceInfo.ip || _('Unknown');
			statusFields.port.textContent = serviceInfo.port || _('Unknown');

			statusLoaded = true;
			updateControls();
		}).catch(error => {
			operationMessage.textContent = error.message;
			statusFields.status.textContent = _('Unknown');
			statusLoaded = false;
			updateControls();
		});

		const performAction = action => {
			if (operationInProgress || !canWrite || !statusLoaded) {
				return Promise.resolve();
			}

			operationInProgress = true;
			updateControls();
			operationMessage.textContent = _('Working…');

			return byedpi.action(action).then(() => {
				operationMessage.textContent = _('Operation completed.');
			}).catch(error => {
				operationMessage.textContent = error.message;
			}).finally(() => {
				operationInProgress = false;
				return refreshStatus();
			});
		};

		const informationRows = [
			[ 'version', _('Version') ],
			[ 'status', _('Status') ],
			[ 'autostart', _('Autostart') ],
			[ 'ip', _('Listen Address') ],
			[ 'port', _('Listen Port') ]
		];

		const informationTable = E('div', {
			'class': 'table',
			'style': 'width:100%;max-width:32rem;table-layout:fixed;margin-bottom:1em'
		}, informationRows.map(([ name, title ]) => {
			const valueCell = E('div', {
				'class': 'td',
				'style': 'overflow-wrap:anywhere'
			}, _('Unknown'));

			statusFields[name] = valueCell;

			return E('div', { 'class': 'tr' }, [
				E('div', { 'class': 'td', 'style': 'width:40%;overflow-wrap:anywhere' }, title),
				valueCell
			]);
		}));

		const actionRow = (title, actions) => E('div', {
			'style': 'display:flex;flex-wrap:wrap;align-items:center;gap:.5em 1em;margin:.75em 0'
		}, [
			E('span', { 'style': 'min-width:5em' }, title),
			E('div', { 'style': 'display:flex;flex-wrap:wrap;gap:.5em' }, actions.map(([ action, label, buttonClass ]) => {
				const button = E('button', {
					'type': 'button',
					'class': 'cbi-button ' + buttonClass,
					'disabled': true,
					'click': () => performAction(action)
				}, label);
				actionButtons.push(button);
				return button;
			}))
		]);

		const autorunControls = actionRow(_('Autorun'), [
			[ 'enable', _('Enable'), 'cbi-button-positive' ],
			[ 'disable', _('Disable'), 'cbi-button-negative' ]
		]);
		const serviceControls = actionRow(_('Service'), [
			[ 'start', _('Start'), 'cbi-button-action' ],
			[ 'restart', _('Restart'), 'cbi-button-action' ],
			[ 'stop', _('Stop'), 'cbi-button-negative' ]
		]);

		poll.add(() => operationInProgress ? Promise.resolve() : refreshStatus(), 5);
		refreshStatus();

		return E('div', { 'class': 'cbi-map' }, [
			E('h2', {}, _('ByeDPI')),
			informationTable,
			autorunControls,
			serviceControls,
			operationMessage
		]);
	}
});

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

		const autostartCheckbox = E('input', {
			'type': 'checkbox',
			'disabled': true
		});

		let operationInProgress = false;
		let statusLoaded = false;

		const updateControls = () => {
			const disabled = operationInProgress || !canWrite || !statusLoaded;

			actionButtons.forEach(button => { button.disabled = disabled; });
			autostartCheckbox.disabled = disabled;
		};

		const refreshStatus = () => byedpi.status().then(response => {
			const serviceInfo = byedpi.serviceInfo(response);

			statusFields.version.textContent = response.version || _('Unknown');
			statusFields.status.textContent = serviceInfo.running ? _('Running') : _('Stopped');
			statusFields.autostart.textContent = response.autostart ? _('Enabled') : _('Disabled');
			statusFields.ip.textContent = serviceInfo.ip || _('Unknown');
			statusFields.port.textContent = serviceInfo.port || _('Unknown');

			if (!operationInProgress) {
				autostartCheckbox.checked = !!response.autostart;
			}

			statusLoaded = true;
			updateControls();
		}).catch(error => {
			operationMessage.textContent = error.message;
			statusFields.status.textContent = _('Unknown');
			statusLoaded = false;
			updateControls();
		});

		const performAction = action => {
			if (operationInProgress) {
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

		autostartCheckbox.addEventListener('change', () =>
			performAction(autostartCheckbox.checked ? 'enable' : 'disable'));

		const informationRows = [
			[ 'version', _('Version') ],
			[ 'status', _('Status') ],
			[ 'autostart', _('Autostart') ],
			[ 'ip', _('Listen Address') ],
			[ 'port', _('Listen Port') ]
		];

		const informationTable = E('div', { 'class': 'table' }, informationRows.map(([ name, title ]) => {
			const valueCell = E('div', {
				'class': 'td',
				'style': 'overflow-wrap:anywhere'
			}, _('Unknown'));

			statusFields[name] = valueCell;

			return E('div', { 'class': 'tr' }, [
				E('div', { 'class': 'td' }, title),
				valueCell
			]);
		}));

		const serviceActions = [
			[ 'start', _('Start') ],
			[ 'stop', _('Stop') ],
			[ 'restart', _('Restart') ]
		];

		for (const [ action, title ] of serviceActions) {
			actionButtons.push(E('button', {
				'class': 'cbi-button cbi-button-action',
				'disabled': true,
				'click': () => performAction(action),
				'style': 'margin:0 .5em .5em 0'
			}, title));
		}

		poll.add(() => operationInProgress ? Promise.resolve() : refreshStatus(), 5);
		refreshStatus();

		return E('div', { 'class': 'cbi-map' }, [
			E('h2', {}, _('ByeDPI')),
			informationTable,
			E('p', {}, [ E('label', {}, [ autostartCheckbox, ' ', _('Start on boot') ]) ]),
			E('div', {}, actionButtons),
			operationMessage
		]);
	}
});

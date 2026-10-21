// Run with QuickJS: qjs --std -m tests/frontend.js (from the repository root).
const root = 'luci-app-byedpi/htdocs/luci-static/resources/';
let checks = 0;
function assert(value, message) {
	if (!value) throw new Error(message);
	checks++;
}
const rpc = { declare: () => () => Promise.resolve({ ok: true }) };
const extend = { extend: value => value };
const api = new Function('baseclass', 'rpc', '_', std.loadFile(root + 'byedpi.js'))(extend, rpc, x => x);
for (const file of [ 'view/byedpi/service.js', 'view/byedpi/settings.js' ]) {
	new Function(std.loadFile(root + file));
	checks++;
}
assert(api.endpoint([]).port === '1080', 'Default port');
assert(api.endpoint(['--ip', '::1', '--port=1090']).ip === '::1', 'IPv6');
assert(api.endpoint(['-i127.0.0.1', '-p1091']).port === '1091', 'Attached short options');
assert(api.endpoint(['--port', '1090', '--port', '1092']).port === '1092', 'Last value wins');
assert(api.endpoint(['--fake-data', '--ip=unexpected']).ip === '0.0.0.0', 'Consume option arguments');
assert(api.endpoint(['--unknown', 'value']).ip === null, 'Unknown options');
assert(api.endpoint(['--port']).port === null, 'Missing argument');
assert(api.endpoint(['--port=99999']).port === null, 'Invalid port');
assert(api.endpoint(['-Ui127.0.0.1']).ip === '127.0.0.1', 'Short option group');
let info = api.serviceInfo({ service: '{}', cmd_opts: '--port=1093', port: '1081' });
assert(!info.running && info.port === '1093', 'Custom options override individual values');
info = api.serviceInfo({ service: '{}', cmd_opts: '--fake-data *', ip: '127.0.0.1' });
assert(info.ip === null, 'Globbing is ambiguous');
const instance = (ip, port) => ({ running: true, command: ['/usr/bin/ciadpi', '--ip', ip, '--port', port] });
info = api.serviceInfo({ service: JSON.stringify({ byedpi: { instances: { one: instance('::', '1085') } } }), cmd_opts: '--port=9000' });
assert(info.running && info.port === '1085', 'Running procd arguments take precedence over edited config');
info = api.serviceInfo({ service: JSON.stringify({ byedpi: { instances: { one: instance('::', '1085'), two: instance('::', '1086') } } }) });
assert(info.ip === '::' && info.port === null, 'Multiple running listeners');
info = api.serviceInfo({ service: '{}', configured: [{ ip: '::1', port: '1080' }, { ip: '127.0.0.1', port: '1080' }] });
assert(info.ip === null && info.port === '1080', 'Multiple configured listeners');

// Small LuCI/DOM test doubles exercise mode switching and UCI writes.
function element(tag, attrs, children) {
	const node = { tag, attrs: attrs || {}, children: [], listeners: {},
		disabled: attrs != null && attrs.disabled != null,
		appendChild(child) {
			if (child && typeof child === 'object') {
				if (child.parent) child.parent.children = child.parent.children.filter(x => x !== child);
				child.parent = this;
			}
			this.children.push(child);
			return child;
		},
		addEventListener(name, fn) { this.listeners[name] = fn; },
		querySelector() { return null; },
		querySelectorAll(selector) {
			const key = selector.slice(1, -1);
			return this.children.filter(x => x && x.attrs && x.attrs[key] != null)
				.concat(this.children.flatMap(x => x && x.querySelectorAll ? x.querySelectorAll(selector) : []));
		}
	};
	(Array.isArray(children) ? children : children == null ? [] : [children]).forEach(x => node.appendChild(x));
	return node;
}
const values = { cmd_opts: '--split 1', debug: '3', port: '1080', split: ['1', '2+s'] };
const writes = [];
const uci = {
	get: (c, s, o) => o === '.type' ? 'byedpi' : values[o],
	set: (c, s, o, v) => { values[o] = v; writes.push(o); },
	changes: () => Promise.resolve({})
};
const input = { ...values };
function Option(type, name) { this.type = type; this.option = name; }
Option.prototype = {
	formvalue() { return input[this.option] || ''; },
	parse() { writes.push(this.option); return Promise.resolve(); },
	render() { return Promise.resolve(element('div', {}, [this.option])); }
};
function Section() { this.options = []; }
Section.prototype = {
	option(type, name) { const o = new Option(type, name); this.options.push(o); return o; },
	render() { return Promise.all(this.options.map(o => o.render())).then(nodes => element('section', {}, nodes)); }
};
function Map() { this.sections = []; }
Map.prototype = {
	section() { const s = new Section(); this.sections.push(s); return s; },
	render() { return Promise.all(this.sections.map(s => s.render())).then(nodes => element('div', {}, nodes)); }
};
const form = { Map, NamedSection: Section, Flag: 'flag', Value: 'value', TextValue: 'text', DummyValue: 'dummy', DynamicList: 'list' };
const dom = { content(node, children) { node.children = [children]; } };
let editorModal;
const ui = {
	showModal: (title, children) => { editorModal = element('div', {}, children); },
	hideModal: () => {},
	addNotification: () => { throw new Error('Unexpected editor error'); }
};
const editorContent = "# Preserve formatting\nconfig byedpi 'main'\n";
const editorApi = { ...api, read: () => Promise.resolve({ content: editorContent, revision: 'revision' }) };
const settings = new Function('view', 'form', 'uci', 'ui', 'dom', 'byedpi', 'E', '_', 'L', std.loadFile(root + 'view/byedpi/settings.js'))(
	extend, form, uci, ui, dom, editorApi, element, x => x, { hasViewPermission: () => true });
const settingsNode = await settings.render();
const descendants = node => node && typeof node === 'object'
	? [ node ].concat((node.children || []).flatMap(descendants)) : [];
const editorButton = node => descendants(node).find(child => child.tag === 'button' && child.children.includes('Edit configuration file'));
assert(!editorButton(settingsNode).disabled, 'File editor is enabled with write access (disabled=false must not become an HTML attribute)');
await editorButton(settingsNode).attrs.click();
assert(editorModal != null, 'Editor button opens the configuration editor');
assert(descendants(editorModal).find(node => node.tag === 'textarea').value === editorContent, 'Editor loads the current configuration with formatting');
assert(!descendants(editorModal).find(node => node.tag === 'button' && node.children.includes('Save')).disabled, 'Editor save is enabled');
let fields = settings.formHost.querySelectorAll('[data-byedpi-individual]');
assert(fields.length === 37, 'All individual init options rendered: ' + fields.length);
assert(fields.every(node => node.disabled), 'Custom mode disables fields');
const options = settings.map.sections[0].options;
const portOption = options.find(o => o.option === 'port');
await portOption.parse('main');
assert(writes.length === 0, 'Disabled fields never overwrite UCI values');
input.cmd_opts = '';
settings.updateMode();
assert(fields.every(node => !node.disabled), 'Clearing custom options immediately enables fields');
await portOption.parse('main');
assert(writes.includes('port'), 'Individual fields can now save');
const custom = options.find(o => o.option === 'cmd_opts');
custom.write('main', '--split 1\n--port 1090');
assert(values.cmd_opts === '--split 1 --port 1090', 'Multiline input becomes one UCI string');
custom.write('main', ' --split  1  ');
assert(values.cmd_opts === ' --split  1  ', 'Existing whitespace is preserved');
assert(options.filter(o => o.type === 'list').map(o => o.option).join(',') === 'split,fake_sni,tlsrec', 'UCI list widgets');
assert(options.find(o => o.option === 'debug').cfgvalue('main') === '1' && values.debug === '3', 'Existing debug levels are retained');
options.find(o => o.option === 'debug').write('main', '1');
assert(values.debug === '3', 'Saving an unchanged debug checkbox retains its numeric level');
options.find(o => o.option === 'debug').write('main', '0');
assert(values.debug === '0', 'Changing debug checkbox writes the requested state');

Map.prototype.readonly = true;
const readonlySettings = await settings.render();
assert(editorButton(readonlySettings).disabled, 'File editor stays disabled without write access');
delete Map.prototype.readonly;

// Service actions, polling and read-only access use the same controls as LuCI.
let allowServiceWrites = true;
let autostart = false;
let finishAction;
let serviceFailure = false;
const requestedActions = [];
const pollCallbacks = [];
const serviceApi = {
	serviceInfo: api.serviceInfo,
	status: () => Promise.resolve({ version: '0.17.3-r1', service: '{}', autostart }),
	action: action => {
		requestedActions.push(action);
		return new Promise((resolve, reject) => {
			finishAction = () => {
				if (serviceFailure) reject(new Error('Service action failed'));
				else {
					if (action === 'enable') autostart = true;
					if (action === 'disable') autostart = false;
					resolve();
				}
			};
		});
	}
};
const service = new Function('view', 'poll', 'byedpi', 'E', '_', 'L', std.loadFile(root + 'view/byedpi/service.js'))(
	extend, { add: (callback, interval) => { pollCallbacks.push(callback); assert(interval === 5, 'Service polls every five seconds'); } },
	serviceApi, element, x => x, { hasViewPermission: () => allowServiceWrites });
const serviceNode = service.render();
await pollCallbacks[0]();
const serviceButtons = descendants(serviceNode).filter(node => node.tag === 'button');
assert(serviceButtons.map(button => button.children[0]).join(',') === 'Enable,Disable,Start,Restart,Stop', 'Autorun and daemon button order');
assert(serviceButtons.every(button => !button.disabled), 'Actions become available after status loads');
assert(serviceButtons.filter(button => button.attrs.class.includes('negative')).map(button => button.children[0]).join(',') === 'Disable,Stop', 'Disable and Stop use the red LuCI button class');
assert(descendants(serviceNode).some(node => node.textContent === '0.17.3-r1'), 'The installed package version is displayed');
for (const [index, action] of ['enable', 'disable', 'start', 'restart', 'stop'].entries()) {
	const pending = serviceButtons[index].attrs.click();
	assert(serviceButtons.every(button => button.disabled), 'All actions are blocked during ' + action);
	await serviceButtons[index].attrs.click();
	assert(requestedActions.length === index + 1, 'Repeated clicks do not repeat ' + action);
	finishAction();
	await pending;
	assert(requestedActions[index] === action, 'The correct RPC action is sent for ' + action);
	assert(serviceButtons.every(button => !button.disabled), 'Controls recover after ' + action);
	if (action === 'enable' || action === 'disable') {
		assert(descendants(serviceNode).some(node => node.textContent === (action === 'enable' ? 'Enabled' : 'Disabled')), 'Autostart status refreshes after ' + action);
	}
}
serviceFailure = true;
const failedAction = serviceButtons[2].attrs.click();
finishAction();
await failedAction;
assert(descendants(serviceNode).some(node => node.textContent === 'Service action failed'), 'RPC action errors are visible');
allowServiceWrites = false;
const readonlyService = service.render();
await pollCallbacks[1]();
assert(descendants(readonlyService).filter(node => node.tag === 'button').every(button => button.disabled), 'Read-only sessions cannot control service or autorun');
console.log(`${checks} frontend checks passed`);

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
	set: (c, s, o, v) => { values[o] = v; writes.push(o); }
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
const settings = new Function('view', 'form', 'uci', 'ui', 'dom', 'byedpi', 'E', '_', 'L', std.loadFile(root + 'view/byedpi/settings.js'))(
	extend, form, uci, {}, dom, api, element, x => x, { hasViewPermission: () => true });
await settings.render();
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
console.log(`${checks} frontend checks passed`);

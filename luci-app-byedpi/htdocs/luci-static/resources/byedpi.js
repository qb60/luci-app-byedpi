'use strict';
'require baseclass';
'require rpc';

const callStatus = rpc.declare({
	object: 'luci.byedpi',
	method: 'status',
	expect: {}
});

const callAction = rpc.declare({
	object: 'luci.byedpi',
	method: 'action',
	params: [ 'action' ],
	expect: {}
});

const callRead = rpc.declare({
	object: 'luci.byedpi',
	method: 'read',
	expect: {}
});

const callWrite = rpc.declare({
	object: 'luci.byedpi',
	method: 'write',
	params: [ 'content', 'revision' ],
	expect: {}
});

const optionsWithValues = new Set([
	'ip', 'port', 'pidfile', 'conn-ip', 'buf-size', 'max-conn', 'debug',
	'auto', 'auto-mode', 'cache-ttl', 'timeout', 'copy', 'cache-file',
	'proto', 'hosts', 'pf', 'round', 'split', 'disorder', 'oob', 'disoob',
	'fake', 'fake-sni', 'ttl', 'fake-data', 'fake-offset', 'fake-tls-mod',
	'oob-data', 'mod-http', 'tlsrec', 'tlsminor', 'udp-fake', 'def-ttl',
	'await-int', 'protect-path', 'ipset'
]);

const flagOptions = new Set([
	'daemon', 'no-domain', 'no-ipv6', 'no-udp', 'transparent', 'tfo',
	'md5sig', 'wait-send', 'drop-sack'
]);

function checkResponse(response) {
	if (!response || !response.ok) {
		const message = response && response.error
			? _(response.error)
			: _('The ByeDPI RPC request failed.');

		throw new Error(message);
	}

	return response;
}

// The init script splits cmd_opts on whitespace. It does not interpret quotes
// inside a UCI value as shell quoting. Unknown syntax must not imply a listener.
function parseEndpoint(argumentsList) {
	let ip = '0.0.0.0';
	let port = '1080';

	const unknownEndpoint = { ip: null, port: null };

	for (let argumentIndex = 0; argumentIndex < argumentsList.length; argumentIndex++) {
		const argument = argumentsList[argumentIndex];

		if (argument === '--') {
			break;
		}

		if (argument.startsWith('--')) {
			const match = /^--([^=]+)(?:=(.*))?$/.exec(argument);

			if (!match) {
				return unknownEndpoint;
			}

			const optionName = match[1];

			if (flagOptions.has(optionName) && match[2] == null) {
				continue;
			}

			if (!optionsWithValues.has(optionName)) {
				return unknownEndpoint;
			}

			const value = match[2] == null ? argumentsList[++argumentIndex] : match[2];

			if (value == null) {
				return unknownEndpoint;
			}

			if (optionName === 'ip') ip = value;
			if (optionName === 'port') port = value;
		}
		else if (/^-[^-]/.test(argument)) {
			for (let characterIndex = 1; characterIndex < argument.length; characterIndex++) {
				const optionCharacter = argument[characterIndex];

				if ('DNXUEFSZY'.includes(optionCharacter)) {
					continue;
				}

				if (!'wipIbcxALuTByKHVRsdoqfntlOQeMrmagWPj'.includes(optionCharacter)) {
					return unknownEndpoint;
				}

				const value = argument.substring(characterIndex + 1) || argumentsList[++argumentIndex];

				if (value == null) {
					return unknownEndpoint;
				}

				if (optionCharacter === 'i') ip = value;
				if (optionCharacter === 'p') port = value;

				break;
			}
		}
		else {
			return unknownEndpoint;
		}
	}

	const validPort = /^\d+$/.test(port || '') && +port > 0 && +port <= 65535;

	return { ip: ip || null, port: validPort ? port : null };
}

function getServiceInfo(response) {
	const serviceState = JSON.parse(response.service || '{}');
	const instances = Object.values((serviceState.byedpi || {}).instances || {});
	const runningInstances = instances.filter(instance => instance.running);

	let endpoints;

	if (runningInstances.length) {
		endpoints = runningInstances.map(instance => Array.isArray(instance.command)
			? parseEndpoint(instance.command.slice(1))
			: { ip: null, port: null });
	}
	else if (response.cmd_opts) {
		const ambiguousArguments = /[\*?\[\]'"\\]/.test(response.cmd_opts);

		endpoints = [ ambiguousArguments
			? { ip: null, port: null }
			: parseEndpoint(response.cmd_opts.trim().split(/\s+/)) ];
	}
	else {
		const configurations = response.configured && response.configured.length
			? response.configured
			: [ response ];

		endpoints = configurations.map(configuration => ({
			ip: configuration.ip || '0.0.0.0',
			port: configuration.port || '1080'
		}));
	}

	const commonValue = propertyName => {
		const firstValue = endpoints.length ? endpoints[0][propertyName] : null;

		return firstValue && endpoints.every(endpoint => endpoint[propertyName] === firstValue)
			? firstValue
			: null;
	};

	return {
		running: runningInstances.length > 0,
		ip: commonValue('ip'),
		port: commonValue('port')
	};
}

return baseclass.extend({
	status: () => callStatus().then(checkResponse),
	action: action => callAction(action).then(checkResponse),
	read: () => callRead().then(checkResponse),
	write: (content, revision) => callWrite(content, revision).then(checkResponse),
	endpoint: parseEndpoint,
	serviceInfo: getServiceInfo
});

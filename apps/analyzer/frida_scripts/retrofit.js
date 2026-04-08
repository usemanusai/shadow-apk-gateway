/**
 * Retrofit Interceptor — Frida Hook Script
 * 
 * Hooks Retrofit 2.x ServiceMethod.invoke() to capture API method metadata.
 * Correlates with OkHttp-level traces via method signature.
 */

'use strict';

Java.perform(function () {
    const System = Java.use('java.lang.System');

    // Try hooking Retrofit's HttpServiceMethod (Retrofit 2.6+)
    let hooked = false;
    
    try {
        const HttpServiceMethod = Java.use('retrofit2.HttpServiceMethod');
        HttpServiceMethod.invoke.implementation = function (args) {
            const startTime = System.currentTimeMillis();
            
            let methodInfo = {};
            try {
                const requestFactory = this.requestFactory.value;
                methodInfo.method = requestFactory.httpMethod.value;
                methodInfo.relativeUrl = requestFactory.relativeUrl.value;
                methodInfo.baseUrl = requestFactory.baseUrl.value.toString();
                methodInfo.isFormEncoded = requestFactory.isFormEncoded.value;
                methodInfo.isMultipart = requestFactory.isMultipart.value;
            } catch (e) {
                // Older Retrofit version - extract what we can
            }
            
            // Capture argument values
            let argValues = [];
            if (args !== null) {
                for (let i = 0; i < args.length; i++) {
                    try {
                        argValues.push(args[i] !== null ? args[i].toString() : 'null');
                    } catch (e) {
                        argValues.push('<unparseable>');
                    }
                }
            }

            const result = this.invoke(args);

            send({
                type: 'retrofit',
                timestampMs: startTime.valueOf(),
                method: methodInfo.method || 'UNKNOWN',
                url: (methodInfo.baseUrl || '') + (methodInfo.relativeUrl || ''),
                baseUrl: methodInfo.baseUrl || '',
                relativeUrl: methodInfo.relativeUrl || '',
                isFormEncoded: methodInfo.isFormEncoded || false,
                isMultipart: methodInfo.isMultipart || false,
                arguments: argValues,
                invokingClass: 'retrofit2.HttpServiceMethod',
                invokingMethod: 'invoke',
                callStack: getCallStack()
            });
            
            return result;
        };
        hooked = true;
        console.log('[retrofit.js] Hooked HttpServiceMethod.invoke');
    } catch (e) {
        console.log('[retrofit.js] HttpServiceMethod not found, trying ServiceMethod...');
    }

    if (!hooked) {
        try {
            const ServiceMethod = Java.use('retrofit2.ServiceMethod');
            ServiceMethod.invoke.implementation = function (args) {
                const startTime = System.currentTimeMillis();
                
                let argValues = [];
                if (args !== null) {
                    for (let i = 0; i < args.length; i++) {
                        try {
                            argValues.push(args[i] !== null ? args[i].toString() : 'null');
                        } catch (e) {
                            argValues.push('<unparseable>');
                        }
                    }
                }

                const result = this.invoke(args);

                send({
                    type: 'retrofit',
                    timestampMs: startTime.valueOf(),
                    method: 'UNKNOWN',
                    url: '',
                    arguments: argValues,
                    invokingClass: 'retrofit2.ServiceMethod',
                    invokingMethod: 'invoke',
                    callStack: getCallStack()
                });

                return result;
            };
            console.log('[retrofit.js] Hooked ServiceMethod.invoke');
        } catch (e) {
            console.log('[retrofit.js] No Retrofit classes found. Skipping.');
        }
    }

    function getCallStack() {
        try {
            const trace = Java.use('java.lang.Thread').currentThread().getStackTrace();
            const stack = [];
            for (let i = 0; i < Math.min(trace.length, 15); i++) {
                stack.push(trace[i].toString());
            }
            return stack;
        } catch (e) {
            return [];
        }
    }
});

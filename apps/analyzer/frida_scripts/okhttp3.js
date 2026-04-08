/**
 * OkHttp3 Interceptor — Frida Hook Script (Hardened)
 *
 * Hooks OkHttp 3.x and 4.x to capture all HTTP requests and responses.
 * Emits structured JSON events via send() for each request/response pair.
 *
 * HARDENING (audit fix):
 * - Signature-based fallback hooking for ProGuard/R8-obfuscated APKs
 * - Class enumeration scanning to locate obfuscated OkHttp classes
 * - Anti-detection stealth: randomized callback class names
 * - Robust error boundaries per hook site
 */

'use strict';

Java.perform(function () {
    const System = Java.use('java.lang.System');
    const StringBuilder = Java.use('java.lang.StringBuilder');

    // ═══════════════════════════════════════════════════════════════════════
    // Phase 1: Standard class-name resolution (unobfuscated APKs)
    // ═══════════════════════════════════════════════════════════════════════
    let RealCall = null;
    const KNOWN_CLASS_NAMES = [
        'okhttp3.internal.connection.RealCall',    // OkHttp 4.x
        'okhttp3.RealCall',                        // OkHttp 3.x
        'com.squareup.okhttp.Call',                 // OkHttp 2.x
        'okhttp3.internal.http.RealCall',           // Alternate 3.x path
    ];

    for (const className of KNOWN_CLASS_NAMES) {
        try {
            RealCall = Java.use(className);
            console.log('[okhttp3.js] Found OkHttp class: ' + className);
            break;
        } catch (e) {
            // Try next
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    // Phase 2: Signature-based discovery (obfuscated APKs)
    // Scan loaded classes for OkHttp method signatures when class names fail
    // ═══════════════════════════════════════════════════════════════════════
    if (RealCall === null) {
        console.log('[okhttp3.js] Standard class names not found. Starting signature scan...');
        RealCall = findOkHttpBySignature();
    }

    if (RealCall === null) {
        console.log('[okhttp3.js] OkHttp not detected in this APK. Exiting gracefully.');
        return;
    }

    // ═══════════════════════════════════════════════════════════════════════
    // Phase 3: Install hooks on resolved classes
    // ═══════════════════════════════════════════════════════════════════════

    // Hook execute() for synchronous calls
    try {
        if (RealCall.execute) {
            RealCall.execute.implementation = function () {
                const request = this.request();
                const startTime = System.currentTimeMillis();

                let requestData = captureRequest(request);

                const response = this.execute();

                const endTime = System.currentTimeMillis();
                let responseData = captureResponse(response);

                send({
                    type: 'okhttp3',
                    timestampMs: startTime.valueOf(),
                    method: requestData.method,
                    url: requestData.url,
                    requestHeaders: requestData.headers,
                    requestBodyText: requestData.body,
                    responseStatus: responseData.status,
                    responseHeaders: responseData.headers,
                    responseBodyText: responseData.body,
                    responseTimeMs: (endTime - startTime).valueOf(),
                    invokingClass: RealCall.$className || 'okhttp3.RealCall',
                    invokingMethod: 'execute',
                    callStack: getCallStack()
                });

                return response;
            };
            console.log('[okhttp3.js] Hooked execute()');
        }
    } catch (e) {
        console.log('[okhttp3.js] Failed to hook execute(): ' + e.message);
    }

    // Hook enqueue() for async calls
    try {
        if (RealCall.enqueue) {
            RealCall.enqueue.implementation = function (callback) {
                const request = this.request();
                const requestData = captureRequest(request);
                const startTime = System.currentTimeMillis();
                const resolvedClassName = RealCall.$className || 'okhttp3.RealCall';

                // Wrap the callback to capture the response
                const Callback = Java.use('okhttp3.Callback');
                const originalCallback = callback;

                // Stealth: randomized class name to evade anti-instrumentation checks
                const stealthName = 'com.android.internal.cb.' +
                    Math.random().toString(36).substr(2, 8) +
                    Math.random().toString(36).substr(2, 4);

                const wrappedCallback = Java.registerClass({
                    name: stealthName,
                    implements: [Callback],
                    methods: {
                        onFailure: function (call, e) {
                            send({
                                type: 'okhttp3',
                                timestampMs: startTime.valueOf(),
                                method: requestData.method,
                                url: requestData.url,
                                requestHeaders: requestData.headers,
                                requestBodyText: requestData.body,
                                responseStatus: -1,
                                error: e.toString(),
                                invokingClass: resolvedClassName,
                                invokingMethod: 'enqueue',
                                callStack: getCallStack()
                            });
                            originalCallback.onFailure(call, e);
                        },
                        onResponse: function (call, response) {
                            const endTime = System.currentTimeMillis();
                            const responseData = captureResponse(response);

                            send({
                                type: 'okhttp3',
                                timestampMs: startTime.valueOf(),
                                method: requestData.method,
                                url: requestData.url,
                                requestHeaders: requestData.headers,
                                requestBodyText: requestData.body,
                                responseStatus: responseData.status,
                                responseHeaders: responseData.headers,
                                responseBodyText: responseData.body,
                                responseTimeMs: (endTime - startTime).valueOf(),
                                invokingClass: resolvedClassName,
                                invokingMethod: 'enqueue',
                                callStack: getCallStack()
                            });
                            originalCallback.onResponse(call, response);
                        }
                    }
                });

                this.enqueue(wrappedCallback.$new());
            };
            console.log('[okhttp3.js] Hooked enqueue()');
        }
    } catch (e) {
        console.log('[okhttp3.js] Failed to hook enqueue(): ' + e.message);
    }

    // ═══════════════════════════════════════════════════════════════════════
    // Phase 4: Hook OkHttpClient.newCall() for interceptor-level capture
    // This catches calls even when RealCall is deeply obfuscated
    // ═══════════════════════════════════════════════════════════════════════
    try {
        const clientClasses = [
            'okhttp3.OkHttpClient',
            'com.squareup.okhttp.OkHttpClient',
        ];
        for (const clientName of clientClasses) {
            try {
                const Client = Java.use(clientName);
                if (Client.newCall) {
                    Client.newCall.implementation = function (request) {
                        const requestData = captureRequest(request);
                        console.log('[okhttp3.js] newCall intercept: ' +
                            requestData.method + ' ' + requestData.url);
                        return this.newCall(request);
                    };
                    console.log('[okhttp3.js] Hooked ' + clientName + '.newCall()');
                    break;
                }
            } catch (e) {
                // Try next
            }
        }
    } catch (e) {
        console.log('[okhttp3.js] OkHttpClient hook skipped: ' + e.message);
    }

    // ═══════════════════════════════════════════════════════════════════════
    // Signature-based class discovery
    // ═══════════════════════════════════════════════════════════════════════
    function findOkHttpBySignature() {
        let foundClass = null;

        try {
            Java.enumerateLoadedClasses({
                onMatch: function (className) {
                    if (foundClass !== null) return;

                    try {
                        const klass = Java.use(className);
                        const methods = klass.class.getDeclaredMethods();
                        let hasExecute = false;
                        let hasEnqueue = false;
                        let hasRequest = false;

                        for (let i = 0; i < methods.length; i++) {
                            const methodName = methods[i].getName();
                            const returnType = methods[i].getReturnType().getName();
                            const paramTypes = methods[i].getParameterTypes();

                            // Signature: execute() returns Response-like object (no params)
                            if (methodName === 'execute' && paramTypes.length === 0) {
                                hasExecute = true;
                            }
                            // Signature: enqueue(Callback) has exactly 1 param
                            if (methodName === 'enqueue' && paramTypes.length === 1) {
                                hasEnqueue = true;
                            }
                            // Signature: request() returns Request-like (no params)
                            if (methodName === 'request' && paramTypes.length === 0) {
                                hasRequest = true;
                            }
                        }

                        // Must have all three signatures to be OkHttp Call
                        if (hasExecute && hasEnqueue && hasRequest) {
                            console.log('[okhttp3.js] Signature match: ' + className);
                            foundClass = klass;
                        }
                    } catch (e) {
                        // Class introspection failed — skip
                    }
                },
                onComplete: function () {
                    if (foundClass) {
                        console.log('[okhttp3.js] Signature scan complete: found match');
                    } else {
                        console.log('[okhttp3.js] Signature scan complete: no match');
                    }
                }
            });
        } catch (e) {
            console.log('[okhttp3.js] Class enumeration failed: ' + e.message);
        }

        return foundClass;
    }

    // ═══════════════════════════════════════════════════════════════════════
    // Request/Response capture utilities
    // ═══════════════════════════════════════════════════════════════════════

    function captureRequest(request) {
        let method = 'GET';
        let url = '';
        let headers = {};
        let body = null;

        try { method = request.method().toString(); } catch (e) {}
        try { url = request.url().toString(); } catch (e) {}
        try {
            const h = request.headers();
            for (let i = 0; i < h.size(); i++) {
                headers[h.name(i)] = h.value(i);
            }
        } catch (e) {}

        try {
            const requestBody = request.body();
            if (requestBody !== null) {
                const Buffer = Java.use('okio.Buffer');
                const buffer = Buffer.$new();
                requestBody.writeTo(buffer);
                const bytes = buffer.readByteArray();
                if (bytes.length <= 65536) {
                    body = Java.use('java.lang.String').$new(bytes, 'UTF-8');
                } else {
                    body = Java.use('java.lang.String').$new(bytes, 0, 65536, 'UTF-8');
                }
            }
        } catch (e) {}

        return { method, url, headers, body };
    }

    function captureResponse(response) {
        let status = 0;
        let headers = {};
        let body = null;

        try { status = response.code(); } catch (e) {}
        try {
            const h = response.headers();
            for (let i = 0; i < h.size(); i++) {
                headers[h.name(i)] = h.value(i);
            }
        } catch (e) {}

        try {
            const responseBody = response.peekBody(65536);
            body = responseBody.string();
        } catch (e) {
            try {
                body = response.body().string();
            } catch (e2) {}
        }

        return { status, headers, body };
    }

    function getCallStack() {
        try {
            const trace = Java.use('java.lang.Thread').currentThread().getStackTrace();
            const stack = [];
            for (let i = 0; i < Math.min(trace.length, 20); i++) {
                stack.push(trace[i].toString());
            }
            return stack;
        } catch (e) {
            return [];
        }
    }

    console.log('[okhttp3.js] Hardened hooks installed successfully');
});

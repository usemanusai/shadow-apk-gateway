/**
 * OkHttp3 Interceptor — Frida Hook Script
 * 
 * Hooks OkHttp 3.x and 4.x to capture all HTTP requests and responses.
 * Emits structured JSON events via send() for each request/response pair.
 */

'use strict';

Java.perform(function () {
    const System = Java.use('java.lang.System');
    const StringBuilder = Java.use('java.lang.StringBuilder');
    
    // Try OkHttp 4.x first, fall back to 3.x
    let RealCall = null;
    try {
        RealCall = Java.use('okhttp3.internal.connection.RealCall');
    } catch (e) {
        try {
            RealCall = Java.use('okhttp3.RealCall');
        } catch (e2) {
            console.log('[okhttp3.js] OkHttp RealCall not found, trying alternate paths...');
            try {
                RealCall = Java.use('com.squareup.okhttp.Call');
            } catch (e3) {
                console.log('[okhttp3.js] No OkHttp classes found. Skipping.');
                return;
            }
        }
    }

    // Hook execute() for synchronous calls
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
                invokingClass: 'okhttp3.RealCall',
                invokingMethod: 'execute',
                callStack: getCallStack()
            });
            
            return response;
        };
    }

    // Hook enqueue() for async calls
    if (RealCall.enqueue) {
        RealCall.enqueue.implementation = function (callback) {
            const request = this.request();
            const requestData = captureRequest(request);
            const startTime = System.currentTimeMillis();
            
            // Wrap the callback to capture the response
            const Callback = Java.use('okhttp3.Callback');
            const originalCallback = callback;
            
            const wrappedCallback = Java.registerClass({
                name: 'com.shadow.WrappedCallback' + Math.random().toString(36).substr(2),
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
                            invokingClass: 'okhttp3.RealCall',
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
                            invokingClass: 'okhttp3.RealCall',
                            invokingMethod: 'enqueue',
                            callStack: getCallStack()
                        });
                        originalCallback.onResponse(call, response);
                    }
                }
            });

            this.enqueue(wrappedCallback.$new());
        };
    }

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
            for (let i = 0; i < Math.min(trace.length, 15); i++) {
                stack.push(trace[i].toString());
            }
            return stack;
        } catch (e) {
            return [];
        }
    }

    console.log('[okhttp3.js] Hooks installed successfully');
});

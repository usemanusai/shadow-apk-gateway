/**
 * WebView Interceptor — Frida Hook Script
 * 
 * Hooks WebView.loadUrl(), loadDataWithBaseURL(), evaluateJavascript(),
 * and registered JS bridge interface methods.
 */

'use strict';

Java.perform(function () {
    const System = Java.use('java.lang.System');
    const WebView = Java.use('android.webkit.WebView');

    // Hook loadUrl
    WebView.loadUrl.overload('java.lang.String').implementation = function (url) {
        send({
            type: 'webview',
            subtype: 'loadUrl',
            timestampMs: System.currentTimeMillis().valueOf(),
            url: url,
            invokingClass: 'android.webkit.WebView',
            invokingMethod: 'loadUrl',
            callStack: getCallStack()
        });
        return this.loadUrl(url);
    };

    // Hook loadUrl with headers
    try {
        WebView.loadUrl.overload('java.lang.String', 'java.util.Map').implementation = function (url, headers) {
            let headerObj = {};
            try {
                const entries = headers.entrySet().toArray();
                for (let i = 0; i < entries.length; i++) {
                    headerObj[entries[i].getKey().toString()] = entries[i].getValue().toString();
                }
            } catch (e) {}

            send({
                type: 'webview',
                subtype: 'loadUrl',
                timestampMs: System.currentTimeMillis().valueOf(),
                url: url,
                requestHeaders: headerObj,
                invokingClass: 'android.webkit.WebView',
                invokingMethod: 'loadUrl',
                callStack: getCallStack()
            });
            return this.loadUrl(url, headers);
        };
    } catch (e) {}

    // Hook loadDataWithBaseURL
    try {
        WebView.loadDataWithBaseURL.implementation = function (baseUrl, data, mimeType, encoding, historyUrl) {
            send({
                type: 'webview',
                subtype: 'loadDataWithBaseURL',
                timestampMs: System.currentTimeMillis().valueOf(),
                url: baseUrl || '',
                requestBodyText: data ? data.substring(0, Math.min(data.length, 65536)) : null,
                mimeType: mimeType,
                encoding: encoding,
                invokingClass: 'android.webkit.WebView',
                invokingMethod: 'loadDataWithBaseURL',
                callStack: getCallStack()
            });
            return this.loadDataWithBaseURL(baseUrl, data, mimeType, encoding, historyUrl);
        };
    } catch (e) {}

    // Hook evaluateJavascript
    try {
        WebView.evaluateJavascript.implementation = function (script, callback) {
            send({
                type: 'webview',
                subtype: 'evaluateJavascript',
                timestampMs: System.currentTimeMillis().valueOf(),
                url: 'javascript:' + (script ? script.substring(0, Math.min(script.length, 4096)) : ''),
                invokingClass: 'android.webkit.WebView',
                invokingMethod: 'evaluateJavascript',
                callStack: getCallStack()
            });
            return this.evaluateJavascript(script, callback);
        };
    } catch (e) {}

    // Hook addJavascriptInterface to capture bridge registrations
    try {
        WebView.addJavascriptInterface.implementation = function (obj, name) {
            send({
                type: 'webview',
                subtype: 'addJavascriptInterface',
                timestampMs: System.currentTimeMillis().valueOf(),
                interfaceName: name,
                interfaceClass: obj.$className || obj.getClass().getName(),
                invokingClass: 'android.webkit.WebView',
                invokingMethod: 'addJavascriptInterface',
            });

            // Hook the bridge interface methods
            try {
                const bridgeClass = obj.getClass();
                const methods = bridgeClass.getDeclaredMethods();
                for (let i = 0; i < methods.length; i++) {
                    const method = methods[i];
                    if (method.isAnnotationPresent(Java.use('android.webkit.JavascriptInterface').class)) {
                        hookBridgeMethod(obj.$className, method.getName());
                    }
                }
            } catch (e) {
                console.log('[webview.js] Could not hook bridge methods: ' + e);
            }

            return this.addJavascriptInterface(obj, name);
        };
    } catch (e) {}

    function hookBridgeMethod(className, methodName) {
        try {
            const cls = Java.use(className);
            if (cls[methodName]) {
                cls[methodName].implementation = function () {
                    const args = [];
                    for (let i = 0; i < arguments.length; i++) {
                        args.push(arguments[i] !== null ? arguments[i].toString() : 'null');
                    }

                    const result = this[methodName].apply(this, arguments);

                    send({
                        type: 'webview',
                        subtype: 'bridgeCall',
                        timestampMs: System.currentTimeMillis().valueOf(),
                        url: 'bridge://' + className + '/' + methodName,
                        method: 'BRIDGE',
                        interfaceClass: className,
                        bridgeMethod: methodName,
                        arguments: args,
                        returnValue: result !== null ? result.toString() : null,
                    });

                    return result;
                };
            }
        } catch (e) {}
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

    console.log('[webview.js] Hooks installed successfully');
});

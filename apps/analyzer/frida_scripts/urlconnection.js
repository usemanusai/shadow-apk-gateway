/**
 * HttpURLConnection Interceptor — Frida Hook Script
 * 
 * Hooks java.net.HttpURLConnection lifecycle to capture request/response data.
 * Uses stateful buffers per connection object to reconstruct request/response pairs.
 */

'use strict';

Java.perform(function () {
    const System = Java.use('java.lang.System');
    const URL = Java.use('java.net.URL');
    const HttpURLConnection = Java.use('java.net.HttpURLConnection');
    
    // State tracking per connection
    const connectionStates = new Map();
    let connectionId = 0;

    // Hook connect()
    HttpURLConnection.connect.implementation = function () {
        const connId = ++connectionId;
        const url = this.getURL().toString();
        const method = this.getRequestMethod();
        
        const state = {
            id: connId,
            url: url,
            method: method,
            requestHeaders: {},
            startTime: System.currentTimeMillis().valueOf(),
        };

        // Capture request headers
        try {
            const headerFields = this.getRequestProperties();
            const entries = headerFields.entrySet().toArray();
            for (let i = 0; i < entries.length; i++) {
                const key = entries[i].getKey();
                const values = entries[i].getValue();
                if (key !== null) {
                    state.requestHeaders[key.toString()] = values.get(0).toString();
                }
            }
        } catch (e) {}

        connectionStates.set(this.hashCode(), state);
        
        return this.connect();
    };

    // Hook getOutputStream() to capture request body
    HttpURLConnection.getOutputStream.implementation = function () {
        const stream = this.getOutputStream();
        const state = connectionStates.get(this.hashCode());
        
        if (state) {
            // Wrap the output stream to capture written data
            // Note: full stream wrapping is complex; we capture what we can
            state.hasBody = true;
        }
        
        return stream;
    };

    // Hook getInputStream() to capture response
    HttpURLConnection.getInputStream.implementation = function () {
        const state = connectionStates.get(this.hashCode());
        
        if (state) {
            const endTime = System.currentTimeMillis();
            let responseStatus = -1;
            let responseHeaders = {};
            
            try { responseStatus = this.getResponseCode(); } catch (e) {}
            
            try {
                const headerFields = this.getHeaderFields();
                const entries = headerFields.entrySet().toArray();
                for (let i = 0; i < entries.length; i++) {
                    const key = entries[i].getKey();
                    const values = entries[i].getValue();
                    if (key !== null) {
                        responseHeaders[key.toString()] = values.get(0).toString();
                    }
                }
            } catch (e) {}

            send({
                type: 'urlconnection',
                timestampMs: state.startTime,
                method: state.method,
                url: state.url,
                requestHeaders: state.requestHeaders,
                responseStatus: responseStatus,
                responseHeaders: responseHeaders,
                responseTimeMs: (endTime - state.startTime).valueOf(),
                invokingClass: 'java.net.HttpURLConnection',
                invokingMethod: 'getInputStream',
                callStack: getCallStack()
            });

            connectionStates.delete(this.hashCode());
        }

        return this.getInputStream();
    };

    // Hook getResponseCode() as additional capture point
    HttpURLConnection.getResponseCode.implementation = function () {
        const code = this.getResponseCode();
        const state = connectionStates.get(this.hashCode());
        
        if (state && !state.responseSent) {
            state.responseCode = code;
        }
        
        return code;
    };

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

    console.log('[urlconnection.js] Hooks installed successfully');
});

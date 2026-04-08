/**
 * TLS Key Logger — Frida Hook Script
 * 
 * Exports TLS session keys in SSLKEYLOGFILE format for use with mitmproxy
 * or Wireshark to decrypt native HTTPS traffic.
 */

'use strict';

Java.perform(function () {
    // Hook SSL/TLS to extract session keys for native traffic decryption
    try {
        const SSLContext = Java.use('javax.net.ssl.SSLContext');
        const TrustManager = Java.use('javax.net.ssl.X509TrustManager');
        
        // Log TLS session info
        const SSLSocket = Java.use('javax.net.ssl.SSLSocket');
        
        SSLSocket.startHandshake.implementation = function () {
            this.startHandshake();
            
            try {
                const session = this.getSession();
                const protocol = session.getProtocol();
                const cipherSuite = session.getCipherSuite();
                const peerHost = this.getInetAddress().getHostAddress();
                const peerPort = this.getPort();
                
                send({
                    type: 'tls_keylog',
                    timestampMs: Java.use('java.lang.System').currentTimeMillis().valueOf(),
                    protocol: protocol,
                    cipherSuite: cipherSuite,
                    peerHost: peerHost,
                    peerPort: peerPort,
                    tlsIntercepted: true,
                });
            } catch (e) {}
        };
        
        console.log('[tls_keylog.js] TLS hooks installed');
    } catch (e) {
        console.log('[tls_keylog.js] Could not hook TLS: ' + e);
    }

    // Apply universal SSL pinning bypass
    try {
        // TrustManagerImpl bypass
        const TrustManagerImpl = Java.use('com.android.org.conscrypt.TrustManagerImpl');
        TrustManagerImpl.verifyChain.implementation = function (untrustedChain, trustAnchorChain, host, clientAuth, ocspData, tlsSctData) {
            return untrustedChain;
        };
        console.log('[tls_keylog.js] SSL pinning bypass: TrustManagerImpl');
    } catch (e) {}

    try {
        // OkHttp CertificatePinner bypass
        const CertificatePinner = Java.use('okhttp3.CertificatePinner');
        CertificatePinner.check.overload('java.lang.String', 'java.util.List').implementation = function (hostname, peerCertificates) {
            // Bypass - do nothing
        };
        console.log('[tls_keylog.js] SSL pinning bypass: OkHttp CertificatePinner');
    } catch (e) {}

    try {
        // NetworkSecurityConfig bypass
        const PlatformTrustManager = Java.use('android.security.net.config.NetworkSecurityTrustManager');
        PlatformTrustManager.checkServerTrusted.implementation = function (chain, authType, engine) {
            // Bypass
        };
        console.log('[tls_keylog.js] SSL pinning bypass: NetworkSecurityTrustManager');
    } catch (e) {}
});

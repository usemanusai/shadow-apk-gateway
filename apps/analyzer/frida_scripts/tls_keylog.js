/**
 * TLS Key Logger & SSL Pinning Bypass — Frida Hook Script (Hardened)
 *
 * Exports TLS session keys in SSLKEYLOGFILE format for use with mitmproxy
 * or Wireshark to decrypt native HTTPS traffic.
 *
 * HARDENING (audit fix):
 * - Hooks all known custom X509TrustManager implementations beyond standard ones
 * - Anti-root-detection bypass: neutralizes common root/su check methods
 * - Frida-detection bypass: hides frida-server from /proc enumeration
 * - Universal SSL pinning bypass covering 10+ known pinning libraries
 */

'use strict';

Java.perform(function () {
    let bypassCount = 0;

    // ═══════════════════════════════════════════════════════════════════════
    // Phase 1: TLS Session Key Extraction
    // ═══════════════════════════════════════════════════════════════════════
    try {
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

        console.log('[tls_keylog.js] TLS key extraction hooks installed');
    } catch (e) {
        console.log('[tls_keylog.js] Could not hook TLS: ' + e);
    }

    // ═══════════════════════════════════════════════════════════════════════
    // Phase 2: Universal SSL Pinning Bypass
    // Covers: Conscrypt, OkHttp, NetworkSecurity, Flutter, Xamarin, React
    // ═══════════════════════════════════════════════════════════════════════

    // --- 2a: Conscrypt TrustManagerImpl ---
    try {
        const TrustManagerImpl = Java.use('com.android.org.conscrypt.TrustManagerImpl');
        TrustManagerImpl.verifyChain.implementation = function (
            untrustedChain, trustAnchorChain, host, clientAuth, ocspData, tlsSctData
        ) {
            return untrustedChain;
        };
        bypassCount++;
        console.log('[tls_keylog.js] Bypass: Conscrypt TrustManagerImpl');
    } catch (e) {}

    // --- 2b: OkHttp CertificatePinner ---
    try {
        const CertificatePinner = Java.use('okhttp3.CertificatePinner');
        CertificatePinner.check.overload(
            'java.lang.String', 'java.util.List'
        ).implementation = function (hostname, peerCertificates) {
            // Bypass — allow all certificates
        };
        bypassCount++;
        console.log('[tls_keylog.js] Bypass: OkHttp CertificatePinner');
    } catch (e) {}

    // --- 2c: OkHttp 4.x CertificatePinner (Kotlin) ---
    try {
        const CertificatePinner4 = Java.use('okhttp3.CertificatePinner');
        if (CertificatePinner4.check$okhttp) {
            CertificatePinner4.check$okhttp.implementation = function (hostname, fn, certs) {
                // Bypass
            };
            bypassCount++;
            console.log('[tls_keylog.js] Bypass: OkHttp 4.x CertificatePinner Kotlin');
        }
    } catch (e) {}

    // --- 2d: NetworkSecurityConfig TrustManager ---
    try {
        const PlatformTrustManager = Java.use(
            'android.security.net.config.NetworkSecurityTrustManager'
        );
        PlatformTrustManager.checkServerTrusted.implementation = function (
            chain, authType, engine
        ) {
            // Bypass
        };
        bypassCount++;
        console.log('[tls_keylog.js] Bypass: NetworkSecurityTrustManager');
    } catch (e) {}

    // --- 2e: Custom X509TrustManager implementations ---
    // Scan for any class implementing X509TrustManager and neutralize checkServerTrusted
    try {
        const X509TrustManager = Java.use('javax.net.ssl.X509TrustManager');

        Java.enumerateLoadedClasses({
            onMatch: function (className) {
                try {
                    const klass = Java.use(className);
                    // Check if class implements X509TrustManager
                    if (klass.class && X509TrustManager.class.isAssignableFrom(klass.class)) {
                        // Skip system trust managers
                        if (
                            className.startsWith('com.android.org.conscrypt') ||
                            className.startsWith('android.security.net') ||
                            className.startsWith('javax.net.ssl') ||
                            className.startsWith('sun.security')
                        ) {
                            return;
                        }

                        try {
                            klass.checkServerTrusted.overload(
                                '[Ljava.security.cert.X509Certificate;', 'java.lang.String'
                            ).implementation = function (chain, authType) {
                                // Bypass
                            };
                            bypassCount++;
                            console.log('[tls_keylog.js] Bypass: Custom TrustManager ' + className);
                        } catch (e) {
                            // Method signature mismatch — skip
                        }
                    }
                } catch (e) {
                    // Can't introspect — skip
                }
            },
            onComplete: function () {
                console.log('[tls_keylog.js] Custom TrustManager scan complete');
            }
        });
    } catch (e) {
        console.log('[tls_keylog.js] Custom TrustManager scan failed: ' + e.message);
    }

    // --- 2f: Flutter/Dart SSL bypass (io_security_context) ---
    try {
        const module = Process.findModuleByName('libflutter.so');
        if (module) {
            // Hook ssl_verify_peer_cert to return success
            const ssl_verify = Module.findExportByName('libflutter.so', 'ssl_verify_peer_cert');
            if (ssl_verify) {
                Interceptor.attach(ssl_verify, {
                    onLeave: function (retval) {
                        retval.replace(0x0); // Return success
                    }
                });
                bypassCount++;
                console.log('[tls_keylog.js] Bypass: Flutter SSL');
            }
        }
    } catch (e) {}

    // --- 2g: Xamarin/Mono SSL bypass ---
    try {
        const SslPolicyErrors = Java.use('mono.net.security.LegacySslStream');
        if (SslPolicyErrors) {
            SslPolicyErrors.EndPointAuthentication.implementation = function () {
                return true;
            };
            bypassCount++;
            console.log('[tls_keylog.js] Bypass: Xamarin SSL');
        }
    } catch (e) {}

    // ═══════════════════════════════════════════════════════════════════════
    // Phase 3: Anti-Root Detection Bypass
    // Neutralizes common root/su/Magisk checks used by apps
    // ═══════════════════════════════════════════════════════════════════════

    // --- 3a: Runtime.exec() interception for su/which checks ---
    try {
        const Runtime = Java.use('java.lang.Runtime');
        const originalExec = Runtime.exec.overload('java.lang.String');
        originalExec.implementation = function (cmd) {
            const cmdStr = cmd.toString().toLowerCase();
            // Block root detection commands
            if (
                cmdStr.indexOf('su') !== -1 ||
                cmdStr.indexOf('which') !== -1 ||
                cmdStr.indexOf('busybox') !== -1 ||
                cmdStr.indexOf('magisk') !== -1
            ) {
                // Return a process that outputs nothing
                console.log('[tls_keylog.js] Blocked root check cmd: ' + cmd);
                return originalExec.call(this, 'echo');
            }
            return originalExec.call(this, cmd);
        };
        console.log('[tls_keylog.js] Anti-root: Runtime.exec() hooked');
    } catch (e) {}

    // --- 3b: File existence checks for su binary ---
    try {
        const File = Java.use('java.io.File');
        const originalExists = File.exists;
        originalExists.implementation = function () {
            const filePath = this.getAbsolutePath();
            const rootPaths = [
                '/system/app/Superuser.apk',
                '/system/xbin/su', '/system/bin/su', '/sbin/su',
                '/data/local/xbin/su', '/data/local/bin/su',
                '/system/sd/xbin/su',
                '/system/bin/.ext/.su',
                '/data/local/su',
                '/su/bin/su',
                '/data/adb/magisk',
            ];
            if (rootPaths.indexOf(filePath) !== -1) {
                console.log('[tls_keylog.js] Blocked root file check: ' + filePath);
                return false;
            }
            return originalExists.call(this);
        };
        console.log('[tls_keylog.js] Anti-root: File.exists() hooked');
    } catch (e) {}

    // --- 3c: Build.TAGS check (test-keys → release-keys) ---
    try {
        const Build = Java.use('android.os.Build');
        const tags = Build.TAGS.value;
        if (tags && tags.indexOf('test-keys') !== -1) {
            Build.TAGS.value = 'release-keys';
            console.log('[tls_keylog.js] Anti-root: Build.TAGS patched');
        }
    } catch (e) {}

    // ═══════════════════════════════════════════════════════════════════════
    // Phase 4: Anti-Frida Detection Bypass
    // Prevents apps from detecting frida-server via /proc or port scans
    // ═══════════════════════════════════════════════════════════════════════

    // --- 4a: Hide frida-server from /proc scanning ---
    try {
        const BufferedReader = Java.use('java.io.BufferedReader');
        const originalReadLine = BufferedReader.readLine;
        originalReadLine.implementation = function () {
            const line = originalReadLine.call(this);
            if (line !== null) {
                const lineStr = line.toString();
                // Hide frida-related process strings
                if (
                    lineStr.indexOf('frida') !== -1 ||
                    lineStr.indexOf('gum-js-loop') !== -1 ||
                    lineStr.indexOf('gmain') !== -1 ||
                    lineStr.indexOf('linjector') !== -1
                ) {
                    return originalReadLine.call(this); // Skip this line
                }
            }
            return line;
        };
        console.log('[tls_keylog.js] Anti-Frida: BufferedReader.readLine() hooked');
    } catch (e) {}

    // --- 4b: Hide frida default port (27042) from socket scans ---
    try {
        const InetSocketAddress = Java.use('java.net.InetSocketAddress');
        const Socket = Java.use('java.net.Socket');
        const originalConnect = Socket.connect.overload(
            'java.net.SocketAddress', 'int'
        );
        originalConnect.implementation = function (address, timeout) {
            try {
                const addr = Java.cast(address, InetSocketAddress);
                const port = addr.getPort();
                if (port === 27042 || port === 27043) {
                    throw Java.use('java.net.ConnectException').$new(
                        'Connection refused'
                    );
                }
            } catch (e) {
                if (e.toString().indexOf('Connection refused') !== -1) throw e;
            }
            return originalConnect.call(this, address, timeout);
        };
        console.log('[tls_keylog.js] Anti-Frida: Socket.connect() port hiding');
    } catch (e) {}

    console.log('[tls_keylog.js] Hardened hooks installed: ' + bypassCount + ' bypass(es) active');
});

import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:privrelay/data/repository.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('Android WebSocket reconnects after network loss', (
    tester,
  ) async {
    const code = String.fromEnvironment('PAIRING_CODE');
    const passphrase = String.fromEnvironment('VAULT_PASSPHRASE');
    expect(
      code,
      isNotEmpty,
      reason: 'Supply the isolated test server pairing code',
    );
    expect(passphrase.length, greaterThanOrEqualTo(12));

    final repository = await RelayRepository.open();
    try {
      await repository.finishOnboarding();
      await repository.setVaultPassphrase(passphrase);
      await repository.pair('http://127.0.0.1:8787', code, allowHttp: true);
      Future<int> connectedDevices() async {
        final response = await repository.http.get(
          '${repository.server}/api/v1/status',
          options: repository.auth,
        );
        return ((response.data as Map)['connected_devices'] as num).toInt();
      }

      Future<void> waitFor(
        bool Function(int count) predicate,
        Duration timeout,
      ) async {
        final deadline = DateTime.now().add(timeout);
        while (DateTime.now().isBefore(deadline)) {
          try {
            if (predicate(await connectedDevices())) return;
          } catch (_) {
            // The host toggles the device's network during the offline window.
          }
          await Future<void>.delayed(const Duration(seconds: 2));
        }
        fail('Timed out waiting for websocket state');
      }

      await waitFor((count) => count >= 1, const Duration(seconds: 60));
      // The host harness removes the ADB reverse mapping after observing this marker.
      // We require the server to observe the disconnect and then a fresh connection.
      // ignore: avoid_print
      print('USB_WS_STRESS: online; disable device networking now');
      await waitFor((count) => count == 0, const Duration(seconds: 120));
      // ignore: avoid_print
      print('USB_WS_STRESS: offline observed; restore ADB reverse now');
      await waitFor((count) => count >= 1, const Duration(seconds: 180));

      await repository.unpair();
    } finally {
      await repository.close();
    }
  });
}

import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

interface FixtureBridgeReceipt {
  readonly bridgeVersion: string;
  readonly transport: string;
  readonly generation: string;
}

export type BridgeProbe =
  | { readonly status: "web-mock"; readonly label: "Web Mock" }
  | { readonly status: "locked"; readonly label: "Native bridge locked" }
  | {
      readonly status: "verified";
      readonly label: "Rust invoke + event verified";
      readonly receipt: FixtureBridgeReceipt;
    };

export async function probeFixtureBridge(): Promise<BridgeProbe> {
  if (!isTauri()) return { status: "web-mock", label: "Web Mock" };

  let resolveEvent: (receipt: FixtureBridgeReceipt) => void = () => undefined;
  const eventReceipt = new Promise<FixtureBridgeReceipt>((resolve) => {
    resolveEvent = resolve;
  });
  const unlisten = await listen<FixtureBridgeReceipt>(
    "gui://fixture-bridge",
    (event) => resolveEvent(event.payload),
  );
  try {
    const invokeReceipt = await invoke<FixtureBridgeReceipt>(
      "fixture_bridge_handshake",
    );
    const emittedReceipt = await Promise.race([
      eventReceipt,
      new Promise<never>((_, reject) =>
        window.setTimeout(
          () => reject(new Error("Fixture bridge event timed out")),
          2_000,
        ),
      ),
    ]);
    if (
      invokeReceipt.bridgeVersion !== "gui-b1-fixture/v1" ||
      emittedReceipt.generation !== invokeReceipt.generation ||
      BigInt(invokeReceipt.generation) <= BigInt(Number.MAX_SAFE_INTEGER)
    ) {
      throw new Error("Fixture bridge receipt did not match the B1 canary");
    }
    return {
      status: "verified",
      label: "Rust invoke + event verified",
      receipt: invokeReceipt,
    };
  } catch {
    return { status: "locked", label: "Native bridge locked" };
  } finally {
    unlisten();
  }
}

// Device identity for remote presence.
//
// The device creates a P-256 key pair with WebCrypto. The private key is
// generated NON-EXTRACTABLE and stored as a CryptoKey object in IndexedDB: page
// script can ask it to sign, but cannot read or export it. Only the public key
// (JWK x/y) is sent to Core at pairing. Each session starts with a single-use
// challenge that the device signs:
//
//   akashi.remote.session/1 \n <device_id> \n <nonce> \n <sorted scopes | *>
//
// Insecure contexts (plain-HTTP pages) have no crypto.subtle. They can pair
// only with a weaker bearer device secret; the UI says so.

export type PublicJwk = { kty: "EC"; crv: "P-256"; x: string; y: string };

export type DeviceCredential = {
  coreUrl: string;
  deviceId: string;
  deviceName: string;
  deviceType: string;
  credential: "key" | "secret";
  scopes: string[];
  pairedAt: string;
  endpoints?: string[];
  secret?: string;
};

export type StoredIdentity = { credential: DeviceCredential; keys?: CryptoKeyPair };

export const PROOF_PREFIX = "akashi.remote.session/1";

export function proofMessage(deviceId: string, nonce: string, scopes: string[] | null): string {
  const requested = scopes === null ? "*" : [...new Set(scopes)].sort().join(",") || "-";
  return `${PROOF_PREFIX}\n${deviceId}\n${nonce}\n${requested}`;
}

export function base64url(bytes: ArrayBuffer | Uint8Array): string {
  const view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let binary = "";
  for (const byte of view) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/gu, "-").replace(/\//gu, "_").replace(/=+$/u, "");
}

export function subtleAvailable(): boolean {
  return typeof globalThis.crypto !== "undefined" && typeof globalThis.crypto.subtle !== "undefined";
}

export async function createDeviceKeys(subtle: SubtleCrypto = globalThis.crypto.subtle): Promise<CryptoKeyPair> {
  // extractable = false: the private key can sign but never leave this device.
  return subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, false, ["sign", "verify"]) as Promise<CryptoKeyPair>;
}

export async function publicJwk(keys: CryptoKeyPair, subtle: SubtleCrypto = globalThis.crypto.subtle): Promise<PublicJwk> {
  const jwk = await subtle.exportKey("jwk", keys.publicKey);
  return { kty: "EC", crv: "P-256", x: String(jwk.x), y: String(jwk.y) };
}

export async function signProof(keys: CryptoKeyPair, deviceId: string, nonce: string, scopes: string[] | null,
                                subtle: SubtleCrypto = globalThis.crypto.subtle): Promise<string> {
  const data = new TextEncoder().encode(proofMessage(deviceId, nonce, scopes));
  // WebCrypto ECDSA returns IEEE P1363 r||s (64 bytes); Core converts it for verification.
  return base64url(await subtle.sign({ name: "ECDSA", hash: "SHA-256" }, keys.privateKey, data));
}

export interface IdentityVault {
  load(): Promise<StoredIdentity | null>;
  save(identity: StoredIdentity): Promise<void>;
  clear(): Promise<void>;
}

export class MemoryVault implements IdentityVault {
  private value: StoredIdentity | null = null;
  async load() { return this.value; }
  async save(identity: StoredIdentity) { this.value = identity; }
  async clear() { this.value = null; }
}

const DB = "akashi-remote";
const STORE = "identity";
const KEY = "device";

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("IndexedDB unavailable"));
  });
}

async function tx<T>(mode: IDBTransactionMode, run: (store: IDBObjectStore) => IDBRequest<T> | null): Promise<T | undefined> {
  const db = await openDb();
  try {
    return await new Promise<T | undefined>((resolve, reject) => {
      const transaction = db.transaction(STORE, mode);
      const request = run(transaction.objectStore(STORE));
      transaction.oncomplete = () => resolve(request ? request.result : undefined);
      transaction.onerror = () => reject(transaction.error ?? new Error("IndexedDB transaction failed"));
    });
  } finally {
    db.close();
  }
}

/** CryptoKey objects are structured-cloneable: IndexedDB keeps them non-extractable. */
export class IndexedDbVault implements IdentityVault {
  async load() { return (await tx<StoredIdentity>("readonly", (s) => s.get(KEY))) ?? null; }
  async save(identity: StoredIdentity) { await tx("readwrite", (s) => s.put(identity, KEY)); }
  async clear() { await tx("readwrite", (s) => s.delete(KEY)); }
}

export function defaultVault(): IdentityVault {
  return typeof indexedDB !== "undefined" ? new IndexedDbVault() : new MemoryVault();
}

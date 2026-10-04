"""Cross-language remote contract: generated protocol file is current; WebCrypto proofs verify in Core."""

import json
import unittest
from pathlib import Path

from app.remote import contract, identity

SHARED = Path(__file__).resolve().parents[2] / "shared" / "contracts" / "remote"


class RemoteContractTests(unittest.TestCase):
    def test_protocol_contract_is_current(self):
        for name, content in contract.artifacts().items():
            self.assertEqual((SHARED / name).read_text(encoding="utf-8"), content,
                             f"{name} is stale: run python -m app.remote.contract --write")

    def test_webcrypto_signature_from_the_frontend_verifies_in_core(self):
        fixture = json.loads((SHARED / "handshake-fixture.json").read_text(encoding="utf-8"))
        jwk = identity.normalize_public_jwk(fixture["public_jwk"])
        message = identity.proof_message(fixture["device_id"], fixture["nonce"], fixture["scopes"])
        self.assertEqual(message.decode("utf-8"), fixture["message"])
        self.assertTrue(identity.verify(jwk, message, fixture["signature"]))
        everything = identity.proof_message(fixture["device_id"], fixture["nonce"], None)
        self.assertEqual(everything.decode("utf-8"), fixture["message_all_scopes"])
        self.assertTrue(identity.verify(jwk, everything, fixture["signature_all_scopes"]))
        # The signature is bound to the scopes: the same proof cannot open a session with others.
        self.assertFalse(identity.verify(jwk, identity.proof_message(fixture["device_id"], fixture["nonce"], ["spatial.view"]),
                                         fixture["signature"]))


if __name__ == "__main__":
    unittest.main()

# AKASHI phone integration

AKASHI keeps telephony transport separate from intelligence:

`Vodafone forwarding -> Verimor SIP -> LiveKit SIP -> AKASHI phone worker -> FastAPI Core`

The LiveKit worker owns realtime audio, turn detection, and interruption. Every
recognized user turn is sent to the existing authenticated `/chat` pipeline, so
persona, memory, model routing, and tools remain centralized in AKASHI Core.
MicroSIP is optional diagnostic equipment only; it is not part of production.

## Runtime processes

Start Core and the phone worker as separate processes from `backend`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
.\.venv\Scripts\python.exe -m app.phone.worker dev
```

When preparing a clean deployment image, prefetch the Silero VAD asset once:

```powershell
.\.venv\Scripts\python.exe -m livekit.agents download-files
```

The worker opens an outbound authenticated WebSocket to `LIVEKIT_URL`; no
public inbound port is required on the worker machine. Core may remain private;
the worker calls `AKASHI_PHONE_CORE_URL` and authenticates with the
normal API token plus a separate worker-only lifecycle token.

## Required server environment

Copy the placeholders from `backend/.env.example` into `backend/.env`:

- `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`: LiveKit project credentials.
- `VERIMOR_SIP_SERVER`, `VERIMOR_SIP_USERNAME`, `VERIMOR_SIP_PASSWORD`: server-only Verimor trunk values. The media worker never returns them to clients.
- `AKASHI_API_TOKEN`: existing Core bearer token.
- `AKASHI_PHONE_WORKER_TOKEN`: a separate random value of at least 32 characters.
- `AKASHI_PHONE_TTS_VOICE`: a Turkish-capable voice ID supported by the configured LiveKit Inference TTS model.
- `AKASHI_PHONE_ENABLED=true`: enables the control plane and worker.
- `AKASHI_OUTBOUND_CALLS_ENABLED=false`: keep this false for inbound-only operation.

`AKASHI_PHONE_STT_MODEL` and `AKASHI_PHONE_TTS_MODEL` are LiveKit Inference
model identifiers. Their defaults are Turkish-capable Cartesia models. They can
be changed server-side without rebuilding any client.

## LiveKit inbound trunk and dispatch

Create these long-lived resources once. Replace the placeholders locally; do
not commit the resulting files.

`inbound-trunk.json`:

```json
{
  "trunk": {
    "name": "AKASHI Verimor inbound",
    "numbers": ["+90XXXXXXXXXX"],
    "media": {
      "onlyListedCodecs": true,
      "codecs": [{ "name": "PCMA" }, { "name": "PCMU" }]
    }
  }
}
```

Create it with credentials that Verimor will present when forwarding the call:

```powershell
lk sip inbound create inbound-trunk.json --auth-user "<SIP_USERNAME>" --auth-pass "<SIP_PASSWORD>"
```

Record the returned trunk ID. Then create `dispatch-rule.json`:

```json
{
  "dispatch_rule": {
    "name": "AKASHI inbound calls",
    "rule": {
      "dispatchRuleIndividual": { "roomPrefix": "akashi-call-" }
    },
    "roomConfig": {
      "agents": [{ "agentName": "akashi-phone" }]
    }
  }
}
```

```powershell
lk sip dispatch create dispatch-rule.json --trunks "<LIVEKIT_INBOUND_TRUNK_ID>"
```

The dispatch `agentName` must match `AKASHI_PHONE_AGENT_NAME`. In Verimor,
configure the incoming route for the Vodafone-forwarded number to the SIP URI
shown by the LiveKit project under **Telephony**. Use the same trunk username
and password if the Verimor route supports authenticated SIP forwarding.

PCMA and PCMU are explicitly selected above. LiveKit also enables both G.711
variants by default, but an explicit list makes the Verimor compatibility
boundary visible and prevents an unexpected codec preference.

## Inbound test

1. Start FastAPI and confirm `GET /health` returns `200`.
2. Start `python -m app.phone.worker dev` and confirm `akashi-phone` registers.
3. In LiveKit, verify the inbound trunk and dispatch rule are listed and linked.
4. Verify the Verimor destination is the LiveKit SIP endpoint, not the PC or MicroSIP.
5. Call the Vodafone number from a second telephone.
6. Confirm LiveKit shows a SIP participant with `sip.phoneNumber` and a dispatched `akashi-phone` agent.
7. AKASHI answers, transcribes the caller, sends the turn through `/chat`, and speaks the response.
8. Open **More -> Calls** in AKASHI to verify caller number, state, duration, transcript, and hang-up.
9. Speak while AKASHI is speaking. The active TTS segment must stop and the new caller turn must take control.
10. End the call and verify `backend/data/private/phone_calls.json` contains the timestamps, duration, transcript, and terminal result.

If signaling succeeds but audio is absent, inspect the SIP SDP: the INVITE and
200 OK must share `PCMA/8000` or `PCMU/8000`, and the advertised RTP address
must be routable.

## Outbound and SMS safety

Outbound calls are rejected unless `AKASHI_OUTBOUND_CALLS_ENABLED=true` and an
outbound trunk ID is configured. Even then, dialing only occurs through an
explicit authenticated `POST /phone/outbound` request with an E.164 number.

SMS has only a disabled service interface. It performs no network operation and
stores no provider credential until a future Verimor API adapter is implemented.

from __future__ import annotations

import json
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from websockets.sync.client import connect


INTERACTIVE_SELECTOR = (
    "a[href],button,input,textarea,select,[role='button'],[role='link'],"
    "[role='checkbox'],[role='radio'],[role='tab'],[contenteditable='true']"
)


class BrowserAutomationError(RuntimeError):
    pass


class ChromiumController:
    """Bounded Chrome DevTools Protocol adapter for an isolated AKASHI profile.

    Only fixed semantic operations are exposed. Callers cannot submit arbitrary
    JavaScript or connect to a remote debugging endpoint.
    """

    def __init__(self, executable: str, port: int, profile_dir: Path) -> None:
        self.executable = str(Path(executable).resolve())
        self.port = port
        self.profile_dir = profile_dir.resolve()
        self.origin = f"http://127.0.0.1:{port}"

    def status(self) -> Dict[str, Any]:
        try:
            version = self._json("/json/version")
            tabs = self.tabs()
            return {
                "ready": True,
                "browser": str(version.get("Browser") or "Chromium")[:160],
                "tab_count": len(tabs),
                "debug_origin": self.origin,
            }
        except BrowserAutomationError:
            return {"ready": False, "tab_count": 0, "debug_origin": self.origin}

    def start(self, initial_url: str = "about:blank") -> Dict[str, Any]:
        current = self.status()
        if current["ready"]:
            return {**current, "reused": True, "verified": True}
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        arguments = [
            self.executable,
            f"--remote-debugging-port={self.port}",
            "--remote-debugging-address=127.0.0.1",
            f"--remote-allow-origins={self.origin}",
            f"--user-data-dir={self.profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            initial_url,
        ]
        subprocess.Popen(
            arguments,
            shell=False,
            cwd=str(Path(self.executable).parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            current = self.status()
            if current["ready"]:
                return {**current, "reused": False, "verified": True}
            time.sleep(0.2)
        raise BrowserAutomationError("AKASHI browser did not expose its loopback automation endpoint.")

    def tabs(self) -> List[Dict[str, Any]]:
        items = self._json("/json/list")
        if not isinstance(items, list):
            raise BrowserAutomationError("Browser returned an invalid target list.")
        return [
            {
                "id": str(item.get("id") or "")[:160],
                "title": str(item.get("title") or "")[:300],
                "url": str(item.get("url") or "")[:2000],
                "type": str(item.get("type") or "")[:40],
                "active": False,
            }
            for item in items
            if item.get("type") == "page" and item.get("id") and item.get("webSocketDebuggerUrl")
        ]

    def snapshot(self, tab_id: Optional[str] = None) -> Dict[str, Any]:
        target = self._target(tab_id)
        expression = r"""(() => {
          const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
          const path = el => {
            if (el.id) return '#' + CSS.escape(el.id);
            const parts = [];
            let node = el;
            while (node && node.nodeType === 1 && parts.length < 6) {
              let part = node.tagName.toLowerCase();
              const parent = node.parentElement;
              if (parent) {
                const peers = [...parent.children].filter(x => x.tagName === node.tagName);
                if (peers.length > 1) part += `:nth-of-type(${peers.indexOf(node) + 1})`;
              }
              parts.unshift(part); node = parent;
            }
            return parts.join(' > ');
          };
          const labelFor = el => {
            if (el.labels && el.labels.length) return norm([...el.labels].map(x => x.innerText).join(' '));
            const id = el.getAttribute('id');
            const label = id ? document.querySelector(`label[for="${CSS.escape(id)}"]`) : null;
            return norm(label && label.innerText);
          };
          const visible = el => {
            const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
          };
          const elements = [...document.querySelectorAll(%SELECTOR%)]
            .filter(visible).slice(0, 240).map((el, index) => {
              const r = el.getBoundingClientRect();
              return {index, tag: el.tagName.toLowerCase(), role: el.getAttribute('role') || (el.tagName === 'BUTTON' ? 'button' : el.tagName === 'A' ? 'link' : el.tagName === 'SELECT' ? 'combobox' : el.type === 'checkbox' ? 'checkbox' : el.type === 'radio' ? 'radio' : el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' ? 'textbox' : ''),
                type: el.getAttribute('type') || '', text: norm(el.innerText || el.value).slice(0, 240),
                label: labelFor(el).slice(0, 200), aria_label: norm(el.getAttribute('aria-label')).slice(0, 200),
                placeholder: norm(el.getAttribute('placeholder')).slice(0, 200), selector: path(el).slice(0, 500),
                disabled: !!el.disabled, checked: !!el.checked,
                bounds: {x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width), height: Math.round(r.height)}};
            });
          return {title: document.title, url: location.href, ready_state: document.readyState,
            text: norm(document.body && document.body.innerText).slice(0, 16000),
            elements, viewport: {width: innerWidth, height: innerHeight, scroll_x: scrollX, scroll_y: scrollY}};
        })()""".replace("%SELECTOR%", json.dumps(INTERACTIVE_SELECTOR))
        result = self._command(target, "Runtime.evaluate", {"expression": expression, "returnByValue": True})
        value = ((result.get("result") or {}).get("value"))
        if not isinstance(value, dict):
            raise BrowserAutomationError("Browser semantic snapshot failed.")
        value["tab_id"] = target["id"]
        try:
            ax = self._command(target, "Accessibility.getFullAXTree", {})
            value["accessibility"] = [
                {
                    "role": str((node.get("role") or {}).get("value") or "")[:80],
                    "name": str((node.get("name") or {}).get("value") or "")[:240],
                }
                for node in list(ax.get("nodes") or [])[:320]
                if (node.get("role") or {}).get("value") not in {"none", "generic", "StaticText", "InlineTextBox"}
            ]
        except BrowserAutomationError:
            value["accessibility"] = []
        return value

    def action(self, operation: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if operation == "new_tab":
            url = str(arguments.get("url") or "about:blank")
            created = self._json(f"/json/new?{quote(url, safe=':/?&=%#')}", method="PUT")
            tab_id = str(created.get("id") or "")
            return {"operation": operation, "tab_id": tab_id, "verified": bool(tab_id), "snapshot": self.snapshot(tab_id)}
        tab_id = str(arguments.get("tab_id") or "") or None
        target = self._target(tab_id)
        if operation == "close_tab":
            result = self._json(f"/json/close/{quote(target['id'])}")
            return {"operation": operation, "tab_id": target["id"], "verified": str(result).casefold() == "target is closing"}
        if operation == "switch_tab":
            self._json(f"/json/activate/{quote(target['id'])}")
            return {"operation": operation, "tab_id": target["id"], "verified": True, "snapshot": self.snapshot(target["id"])}
        if operation == "navigate":
            url = str(arguments.get("url") or "")
            self._command(target, "Page.navigate", {"url": url})
            return self._wait_snapshot(target["id"], operation, expected_url=url)
        if operation in {"back", "forward"}:
            expression = "history.back()" if operation == "back" else "history.forward()"
            self._command(target, "Runtime.evaluate", {"expression": expression})
            return self._wait_snapshot(target["id"], operation)
        if operation == "reload":
            self._command(target, "Page.reload", {"ignoreCache": False})
            return self._wait_snapshot(target["id"], operation)
        if operation == "handle_dialog":
            self._command(target, "Page.handleJavaScriptDialog", {
                "accept": bool(arguments.get("accept")),
                "promptText": str(arguments.get("value") or "")[:2000],
            })
            return {"operation": operation, "verified": True, "snapshot": self.snapshot(target["id"])}
        payload = {
            "operation": operation,
            "target": arguments.get("target") or {},
            "value": str(arguments.get("value") or "")[:20_000],
            "delta": int(arguments.get("delta") or 600),
        }
        expression = self._semantic_action_expression(payload)
        result = self._command(target, "Runtime.evaluate", {"expression": expression, "awaitPromise": True, "returnByValue": True})
        value = ((result.get("result") or {}).get("value"))
        if not isinstance(value, dict) or not value.get("ok"):
            raise BrowserAutomationError(str((value or {}).get("error") or "Semantic browser action failed.")[:500])
        return {"operation": operation, "matched": value.get("matched"), "verified": True, "snapshot": self.snapshot(target["id"])}

    @staticmethod
    def _semantic_action_expression(payload: Dict[str, Any]) -> str:
        encoded = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
        return r"""(async () => {
          const req = %PAYLOAD%; const norm = v => String(v || '').replace(/\s+/g, ' ').trim().toLowerCase();
          if (req.operation === 'scroll') { window.scrollBy({top:req.delta, behavior:'instant'}); return {ok:true}; }
          const visible = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
          const target = req.target || {}; const all = [...document.querySelectorAll(%SELECTOR%)].filter(visible).slice(0,240);
          const labelFor = el => el.labels && el.labels.length ? [...el.labels].map(x => x.innerText).join(' ') : '';
          const matches = el => {
            if (target.selector) { try { return el.matches(target.selector); } catch (_) { return false; } }
            if (target.index !== undefined && target.index !== null) return all.indexOf(el) === Number(target.index);
            const role = el.getAttribute('role') || (el.tagName === 'BUTTON' ? 'button' : el.tagName === 'A' ? 'link' : el.tagName === 'SELECT' ? 'combobox' : el.type === 'checkbox' ? 'checkbox' : el.type === 'radio' ? 'radio' : el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' ? 'textbox' : '');
            if (target.role && norm(role) !== norm(target.role)) return false;
            const hay = norm([el.innerText, el.value, el.getAttribute('aria-label'), el.getAttribute('placeholder'), labelFor(el)].join(' '));
            const needle = norm(target.text || target.label || target.aria_label || target.placeholder || '');
            return !!needle && hay.includes(needle);
          };
          const candidates = all.filter(matches);
          if (candidates.length !== 1) return {ok:false,error:candidates.length ? 'Ambiguous semantic target. Refine the locator.' : 'No semantic element matched the target.'};
          const el = candidates[0];
          if (el.disabled) return {ok:false,error:'Target is disabled.'};
          el.scrollIntoView({block:'center', inline:'center'});
          if (req.operation === 'click') el.click();
          else if (req.operation === 'clear' || req.operation === 'type') {
            el.focus(); const setter = Object.getOwnPropertyDescriptor(el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, 'value');
            const value = req.operation === 'clear' ? '' : req.value;
            if (el.isContentEditable) el.textContent = value;
            else if (setter && setter.set) setter.set.call(el, value); else el.value = value;
            el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true}));
            if ((el.isContentEditable ? el.textContent : el.value) !== value) return {ok:false,error:'Input value did not persist.'};
          } else if (req.operation === 'select') {
            el.value = req.value; el.dispatchEvent(new Event('change', {bubbles:true}));
            if (el.value !== req.value) return {ok:false,error:'Requested select option not present.'};
          } else if (req.operation === 'check') {
            if (!el.checked) el.click();
            if (!el.checked) return {ok:false,error:'Checkbox did not become checked.'};
          } else if (req.operation === 'uncheck') {
            if (el.checked) el.click();
            if (el.checked) return {ok:false,error:'Checkbox did not become unchecked.'};
          } else if (req.operation === 'scroll') window.scrollBy({top:req.delta, behavior:'instant'});
          else return {ok:false,error:'Unsupported semantic operation.'};
          await new Promise(resolve => setTimeout(resolve, 250));
          return {ok:true,matched:{tag:el.tagName.toLowerCase(),text:norm(el.innerText || el.value).slice(0,200)}};
        })()""".replace("%PAYLOAD%", encoded).replace("%SELECTOR%", json.dumps(INTERACTIVE_SELECTOR))

    def _wait_snapshot(self, tab_id: str, operation: str, expected_url: Optional[str] = None) -> Dict[str, Any]:
        deadline = time.monotonic() + 12.0
        latest: Dict[str, Any] = {}
        while time.monotonic() < deadline:
            try:
                latest = self.snapshot(tab_id)
                if latest.get("ready_state") in {"interactive", "complete"} and (not expected_url or latest.get("url") == expected_url):
                    break
            except BrowserAutomationError:
                pass
            time.sleep(0.2)
        verified = bool(latest) and (not expected_url or latest.get("url") == expected_url)
        return {"operation": operation, "tab_id": tab_id, "verified": verified, "snapshot": latest}

    def _target(self, tab_id: Optional[str]) -> Dict[str, Any]:
        items = self._json("/json/list")
        pages = [item for item in items if item.get("type") == "page" and item.get("webSocketDebuggerUrl")]
        target = next((item for item in pages if str(item.get("id")) == tab_id), None) if tab_id else (pages[0] if pages else None)
        if not target:
            raise BrowserAutomationError("No controllable AKASHI browser tab is available.")
        return target

    def _command(self, target: Dict[str, Any], method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        endpoint = str(target.get("webSocketDebuggerUrl") or "")
        if not endpoint.startswith(f"ws://127.0.0.1:{self.port}/") and not endpoint.startswith(f"ws://localhost:{self.port}/"):
            raise BrowserAutomationError("Browser debugging endpoint escaped loopback policy.")
        command_id = int(time.time_ns() % 2_000_000_000)
        try:
            with connect(endpoint, origin=self.origin, open_timeout=3, close_timeout=1) as websocket:
                websocket.send(json.dumps({"id": command_id, "method": method, "params": params}))
                deadline = time.monotonic() + 8.0
                while time.monotonic() < deadline:
                    message = json.loads(websocket.recv(timeout=max(0.1, deadline - time.monotonic())))
                    if message.get("id") != command_id:
                        continue
                    if message.get("error"):
                        raise BrowserAutomationError(str(message["error"].get("message") or "CDP action failed.")[:500])
                    return dict(message.get("result") or {})
        except (OSError, TimeoutError, socket.timeout, json.JSONDecodeError) as exc:
            raise BrowserAutomationError("Browser automation connection failed.") from exc
        raise BrowserAutomationError("Browser automation command timed out.")

    def _json(self, path: str, method: str = "GET") -> Any:
        request = Request(self.origin + path, method=method, headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=3.0) as response:
                if int(response.headers.get("Content-Length") or 0) > 2_000_000:
                    raise BrowserAutomationError("Browser response exceeded the safe size limit.")
                payload = response.read(2_000_001)
            if len(payload) > 2_000_000:
                raise BrowserAutomationError("Browser response exceeded the safe size limit.")
            text = payload.decode("utf-8")
            if path.startswith("/json/close/") and text.strip() == "Target is closing":
                return text.strip()
            if path.startswith("/json/activate/") and text.strip() == "Target activated":
                return text.strip()
            return json.loads(text)
        except (URLError, OSError, ValueError, json.JSONDecodeError) as exc:
            raise BrowserAutomationError("Browser automation endpoint is offline.") from exc

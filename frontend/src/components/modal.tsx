"use client";
import { useEffect, useRef, type ReactNode } from "react";

export function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); }, []);
  return <dialog ref={ref} className="settings-dialog" aria-label={title} onCancel={onClose} onClick={(event) => { if (event.target === ref.current) onClose(); }}>
    <div className="settings-panel"><div className="settings-heading"><div><p className="eyebrow">CONNECTION / SECURITY</p><h3>{title}</h3></div><button type="button" onClick={onClose} aria-label="Ayarları kapat">×</button></div>{children}</div>
  </dialog>;
}

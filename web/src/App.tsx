import { useEffect, useState } from "react";

type Health = { status: string; version: string };

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/v1/health")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setHealth)
      .catch((e: Error) => setError(e.message));
  }, []);

  return (
    <main className="card">
      <h1>PaperTrail</h1>
      {health && <p>版本 {health.version}</p>}
      {error && <p>无法连接服务：{error}</p>}
      {!health && !error && <p>连接中…</p>}
    </main>
  );
}

import type { Simulation } from "../lib/api";

export function SimulationCard({ simulations, onRun }: { simulations: Simulation[]; onRun: () => void }) {
  return <div className="panel" id="simulations"><h3>Simulation Confidence</h3>{simulations.length ? <ul className="compactList">{simulations.slice(0, 5).map((s) => <li key={s.id}>Simulation #{s.id}<span>{s.confidence ?? 0} confidence</span></li>)}</ul> : <p>No simulations saved yet.</p>}<button onClick={onRun}>Run simulation</button></div>;
}

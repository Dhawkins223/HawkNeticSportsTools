"use client";

const transparencyItems = [
  {
    title: "Injury report weighting",
    body: "Player availability is ingested from the league feed twice hourly. We weight questionable tags by 35% minutes reduction and doubtful tags by 80%."
  },
  {
    title: "Travel fatigue",
    body: "Back-to-back legs and cross-country travel increase fatigue penalties. Elevation changes for Denver and Utah add an additional 4% decrement to opponent efficiencies."
  },
  {
    title: "Pace adjustments",
    body: "Base pace is derived from opponent-adjusted possessions per game over the last 10 days. Injury downgrades and blowout risk dampen possessions to avoid overly aggressive overs."
  },
  {
    title: "Blowout risk",
    body: "We translate spread and rest advantage into a win probability curve, projecting garbage-time likelihood that suppresses star usage in lopsided scripts."
  }
];

export default function AboutModelPage() {
  return (
    <div className="space-y-8">
      <header className="space-y-2">
        <h2 className="text-2xl font-semibold text-white">Model transparency</h2>
        <p className="text-sm text-white/60">
          Understand how simulations, injuries, fatigue, and pace inform every EV tag.
        </p>
      </header>
      <section className="grid gap-4 md:grid-cols-2">
        {transparencyItems.map((item) => (
          <article key={item.title} className="card space-y-2 p-6 text-sm text-white/70">
            <h3 className="text-base font-semibold text-white">{item.title}</h3>
            <p>{item.body}</p>
          </article>
        ))}
      </section>
      <section className="card space-y-4 p-6">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-white/60">Data freshness</h3>
        <p className="text-sm text-white/70">
          Simulations refresh every time `/api/sync` completes or a manual SGP run is triggered. Injury events trigger an immediate rerun, and the SGP composer fetches a joint probability snapshot straight from the latest Monte Carlo run.
        </p>
        <p className="text-sm text-white/70">
          Configure provider credentials in `.env.local` to remove any placeholder notices. Without valid keys the API responds with `503` so you always know when data needs refreshing.
        </p>
      </section>
    </div>
  );
}

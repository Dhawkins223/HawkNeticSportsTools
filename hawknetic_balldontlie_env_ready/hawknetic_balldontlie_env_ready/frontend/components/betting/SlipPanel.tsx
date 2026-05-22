"use client";

import { SortableContext, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { useDroppable } from "@dnd-kit/core";
import { CSS } from "@dnd-kit/utilities";
import type { BetSlipLeg, Bookmaker, MarketType, SlipAnalysisResponse } from "../../types/betting";
import { AnalysisPanel } from "./AnalysisPanel";
import { americanToDecimal, formatOdds } from "./marketOptions";
import type { ManualLegInput } from "./useSlipBuilder";

const SEMI_BOLD_FONT_WEIGHT = 600;

function payoutPreview(legs: BetSlipLeg[], stake: number): number {
  if (!legs.length || !stake) return 0;
  const decimal = legs.reduce((product, leg) => product * americanToDecimal(leg.oddsAmerican), 1);
  return stake * decimal;
}

function SortableSlipLeg({
  leg,
  index,
  onRemove,
  onMove,
}: {
  leg: BetSlipLeg;
  index: number;
  onRemove: (id: string) => void;
  onMove: (index: number, direction: -1 | 1) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id: leg.id });
  return (
    <article ref={setNodeRef} className="betSlipLegCard" style={{ transform: CSS.Transform.toString(transform), transition }}>
      <button className="dragHandle" type="button" {...attributes} {...listeners} aria-label={`Drag ${leg.selection}`}>::</button>
      <div>
        <strong>{leg.selection}</strong>
        <p>{leg.eventLabel}</p>
        <small>{leg.marketType.replaceAll("_", " ")} {leg.line ?? ""} · {formatOdds(leg.oddsAmerican)}</small>
      </div>
      <div className="legControls">
        <button type="button" disabled={index === 0} onClick={() => onMove(index, -1)}>Up</button>
        <button type="button" onClick={() => onMove(index, 1)}>Down</button>
        <button type="button" onClick={() => onRemove(leg.id)}>Remove</button>
      </div>
    </article>
  );
}

function SlipDropArea({ children }: { children: React.ReactNode }) {
  const { setNodeRef, isOver } = useDroppable({ id: "slip-drop" });
  return <div ref={setNodeRef} className={`slipDropArea ${isOver ? "isOver" : ""}`}>{children}</div>;
}

function saveButtonLabel(savingSlip: boolean, isAuthenticated: boolean): string {
  if (savingSlip) return "Saving…";
  return isAuthenticated ? "Save slip to my account" : "Sign in to save slip";
}

function ManualEntry({
  manual,
  setManual,
  onAdd,
}: {
  manual: ManualLegInput;
  setManual: (m: ManualLegInput) => void;
  onAdd: () => void;
}) {
  return (
    <details className="manualEntry">
      <summary>Manual market entry</summary>
      <input placeholder="Event label" value={manual.eventLabel} onChange={(e) => setManual({ ...manual, eventLabel: e.target.value })} />
      <select value={manual.marketType} onChange={(e) => setManual({ ...manual, marketType: e.target.value as MarketType })}>
        <option value="moneyline">Moneyline</option>
        <option value="spread">Spread</option>
        <option value="total">Total</option>
        <option value="player_prop">Player prop</option>
        <option value="team_prop">Team prop</option>
        <option value="same_game_parlay">Same game parlay</option>
      </select>
      <input placeholder="Selection" value={manual.selection} onChange={(e) => setManual({ ...manual, selection: e.target.value })} />
      <input placeholder="Line" value={manual.line} onChange={(e) => setManual({ ...manual, line: e.target.value })} />
      <input placeholder="American odds" value={manual.oddsAmerican} onChange={(e) => setManual({ ...manual, oddsAmerican: e.target.value })} />
      <button type="button" onClick={onAdd}>Add manual leg</button>
    </details>
  );
}

export type SlipPanelProps = {
  legs: BetSlipLeg[];
  bookmaker: Bookmaker;
  setBookmaker: (b: Bookmaker) => void;
  stake: number;
  setStake: (n: number) => void;
  manual: ManualLegInput;
  setManual: (m: ManualLegInput) => void;
  onAddManual: () => void;
  onRemove: (id: string) => void;
  onMove: (index: number, direction: -1 | 1) => void;
  onAnalyze: () => void | Promise<void>;
  onSave: () => void | Promise<void>;
  analyzing: boolean;
  analysis: SlipAnalysisResponse | null;
  savingSlip: boolean;
  savedSlipMsg: string | null;
  isAuthenticated: boolean;
};

function SlipHeader({ legCount, testIdSuffix }: { legCount: number; testIdSuffix: string }) {
  return (
    <div className="hnSlipHeader">
      <div>
        <p>Prediction tool · no wagers placed</p>
        <h2>Algorithm Run</h2>
      </div>
      <strong data-testid={`slip-leg-count${testIdSuffix}`}>{legCount}</strong>
    </div>
  );
}

function BookmakerSelector({ bookmaker, setBookmaker, testIdSuffix }: { bookmaker: Bookmaker; setBookmaker: (b: Bookmaker) => void; testIdSuffix: string }) {
  return (
    <label className="hnField">Data source
      <select value={bookmaker} onChange={(event) => setBookmaker(event.target.value as Bookmaker)} data-testid={`bookmaker-select${testIdSuffix}`}>
        <option value="bet365">Reference sportsbook lines</option>
        <option value="manual">Manual entry</option>
      </select>
    </label>
  );
}

function StakeField({ stake, setStake, testIdSuffix }: { stake: number; setStake: (n: number) => void; testIdSuffix: string }) {
  return (
    <label className="hnField">Confidence weight
      <input type="number" min="0" value={stake} onChange={(event) => setStake(Number(event.target.value))} data-testid={`stake-input${testIdSuffix}`} />
    </label>
  );
}

function PayoutPreview({ legs, stake, testIdSuffix }: { legs: BetSlipLeg[]; stake: number; testIdSuffix: string }) {
  return (
    <div className="payoutPreview">
      <span>Projected payout multiple</span>
      <strong data-testid={`payout-preview${testIdSuffix}`}>${payoutPreview(legs, stake).toFixed(2)}</strong>
    </div>
  );
}

function SlipLegsList({
  legs,
  onRemove,
  onMove,
}: {
  legs: BetSlipLeg[];
  onRemove: (id: string) => void;
  onMove: (index: number, direction: -1 | 1) => void;
}) {
  return (
    <SlipDropArea>
      <SortableContext items={legs.map((leg) => leg.id)} strategy={verticalListSortingStrategy}>
        {legs.length ? (
          legs.map((leg, index) => (
            <SortableSlipLeg key={leg.id} leg={leg} index={index} onRemove={onRemove} onMove={onMove} />
          ))
        ) : (
          <div className="hnEmptySlip">
            Click or drag a market here to add it to your algorithm run. This tool predicts — it does not place wagers.
          </div>
        )}
      </SortableContext>
    </SlipDropArea>
  );
}

function RunSaveActions({
  legCount,
  analyzing,
  savingSlip,
  savedSlipMsg,
  isAuthenticated,
  onAnalyze,
  onSave,
  testIdSuffix,
}: {
  legCount: number;
  analyzing: boolean;
  savingSlip: boolean;
  savedSlipMsg: string | null;
  isAuthenticated: boolean;
  onAnalyze: () => void | Promise<void>;
  onSave: () => void | Promise<void>;
  testIdSuffix: string;
}) {
  return (
    <>
      <button
        className="analyzeButton"
        type="button"
        disabled={!legCount || analyzing}
        onClick={() => onAnalyze()}
        data-testid={`run-algorithm-button${testIdSuffix}`}
      >
        {analyzing ? "Running algorithm..." : "Run Algorithm"}
      </button>
      <button
        type="button"
        disabled={!legCount || savingSlip}
        onClick={() => onSave()}
        data-testid={`save-slip-button${testIdSuffix}`}
        style={{
          marginTop: "0.4rem",
          padding: "0.65rem 1rem",
          borderRadius: "999px",
          border: "1px solid rgba(216,246,58,0.4)",
          background: "transparent",
          color: "#d8f63a",
          cursor: legCount && !savingSlip ? "pointer" : "not-allowed",
          fontWeight: SEMI_BOLD_FONT_WEIGHT,
        }}
      >
        {saveButtonLabel(savingSlip, isAuthenticated)}
      </button>
      {savedSlipMsg && (
        <div data-testid={`saved-slip-msg${testIdSuffix}`} style={{ fontSize: "0.78rem", opacity: 0.8, marginTop: "0.3rem" }}>{savedSlipMsg}</div>
      )}
    </>
  );
}

export function SlipPanel(props: SlipPanelProps & { variant?: "desktop" | "mobile" }) {
  const {
    legs, bookmaker, setBookmaker, stake, setStake,
    manual, setManual, onAddManual, onRemove, onMove,
    onAnalyze, onSave, analyzing, analysis,
    savingSlip, savedSlipMsg, isAuthenticated,
    variant = "desktop",
  } = props;
  // Render the same SlipPanel twice (desktop right-rail + mobile slide-up drawer)
  // — use a testid suffix so the two copies don't collide for E2E tests.
  const sfx = variant === "desktop" ? "" : "-mobile";

  return (
    <aside className="hnSlip" data-testid={`algorithm-slip${sfx}`}>
      <SlipHeader legCount={legs.length} testIdSuffix={sfx} />
      <BookmakerSelector bookmaker={bookmaker} setBookmaker={setBookmaker} testIdSuffix={sfx} />
      <SlipLegsList legs={legs} onRemove={onRemove} onMove={onMove} />
      <ManualEntry manual={manual} setManual={setManual} onAdd={onAddManual} />
      <StakeField stake={stake} setStake={setStake} testIdSuffix={sfx} />
      <PayoutPreview legs={legs} stake={stake} testIdSuffix={sfx} />
      <RunSaveActions
        legCount={legs.length}
        analyzing={analyzing}
        savingSlip={savingSlip}
        savedSlipMsg={savedSlipMsg}
        isAuthenticated={isAuthenticated}
        onAnalyze={onAnalyze}
        onSave={onSave}
        testIdSuffix={sfx}
      />
      {analysis && <AnalysisPanel analysis={analysis} />}
    </aside>
  );
}

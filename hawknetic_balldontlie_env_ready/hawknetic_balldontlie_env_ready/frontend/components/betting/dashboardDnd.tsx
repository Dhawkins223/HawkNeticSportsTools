"use client";

import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import { sortableKeyboardCoordinates } from "@dnd-kit/sortable";
import type { ReactNode } from "react";
import type { BetSlipLeg } from "../../types/betting";
import type { MarketOption } from "./marketOptions";

const OPTION_PREFIX = "option:";
const SLIP_DROP_ID = "slip-drop";

export function useDashboardSensors() {
  return useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
}

type DragEndHandlers = {
  onAddOption: (option: MarketOption) => void;
  onReorderLegs: (oldIndex: number, newIndex: number) => void;
  marketOptions: MarketOption[];
  legs: BetSlipLeg[];
};

function findOptionByActiveId(activeId: string, options: MarketOption[]): MarketOption | undefined {
  return options.find((item) => `${OPTION_PREFIX}${item.id}` === activeId);
}

function findLegIndices(legs: BetSlipLeg[], activeId: string, overId: string): [number, number] | null {
  if (activeId === overId) return null;
  if (!legs.some((leg) => leg.id === activeId)) return null;
  const oldIndex = legs.findIndex((leg) => leg.id === activeId);
  const newIndex = legs.findIndex((leg) => leg.id === overId);
  if (oldIndex === -1 || newIndex === -1) return null;
  return [oldIndex, newIndex];
}

export function makeDragEndHandler({ onAddOption, onReorderLegs, marketOptions, legs }: DragEndHandlers) {
  return function onDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over) return;
    const activeId = String(active.id);
    const overId = String(over.id);
    if (activeId.startsWith(OPTION_PREFIX) && overId === SLIP_DROP_ID) {
      const option = findOptionByActiveId(activeId, marketOptions);
      if (option) onAddOption(option);
      return;
    }
    const indices = findLegIndices(legs, activeId, overId);
    if (indices) onReorderLegs(indices[0], indices[1]);
  };
}

export function DashboardDndProvider({
  onDragEnd,
  children,
}: {
  onDragEnd: (event: DragEndEvent) => void;
  children: ReactNode;
}) {
  const sensors = useDashboardSensors();
  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
      {children}
    </DndContext>
  );
}

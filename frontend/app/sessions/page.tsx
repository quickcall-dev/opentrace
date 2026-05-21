"use client";

import { useState } from "react";
import { DataTable } from "@/components/data-table";
import { CalendarPicker } from "@/components/calendar-picker";

export default function SessionsPage() {
  const [date, setDate] = useState<string | undefined>(undefined);

  return (
    <div className="flex flex-col h-full bg-muted">
      <div className="shrink-0 sticky top-0 z-10 bg-muted border-b border-border">
        <div className="max-w-6xl mx-auto px-4 py-4 flex items-center justify-between">
          <h1 className="text-xl font-semibold text-foreground">
            Sessions
          </h1>
          <CalendarPicker value={date} onChange={setDate} />
        </div>
      </div>
      <div className="flex-1 overflow-auto">
        <div className="max-w-6xl mx-auto px-4 py-4">
          <DataTable date={date} />
        </div>
      </div>
    </div>
  );
}

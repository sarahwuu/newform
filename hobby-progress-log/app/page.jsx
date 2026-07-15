"use client";

import { useState } from "react";
import { seedHobby } from "../lib/seed";
import Capture from "../components/Capture";
import Compare from "../components/Compare";
import Thread from "../components/Thread";

const TABS = ["capture", "compare", "thread"];

export default function Home() {
  const [hobby, setHobby] = useState(seedHobby);
  const [screen, setScreen] = useState("capture");
  const [leftIndex, setLeftIndex] = useState(0); // default: today vs attempt 1

  function saveAttempt({ imageUrl, note }) {
    setHobby((h) => ({
      ...h,
      attempts: [
        ...h.attempts,
        {
          id: `attempt-${h.attempts.length + 1}-${Date.now()}`,
          imageUrl,
          note,
          date: new Date().toISOString(),
          index: h.attempts.length + 1,
        },
      ],
    }));
    setLeftIndex(0);
    setScreen("compare"); // straight to the payoff
  }

  function pickFromThread(i) {
    // the latest attempt is always the fixed right side
    if (i < hobby.attempts.length - 1) setLeftIndex(i);
    setScreen("compare");
  }

  return (
    <main className="pb-24">
      {screen === "capture" && <Capture hobby={hobby} onSave={saveAttempt} />}
      {screen === "compare" && (
        <Compare
          hobby={hobby}
          leftIndex={leftIndex}
          onLeftIndexChange={setLeftIndex}
        />
      )}
      {screen === "thread" && <Thread hobby={hobby} onPick={pickFromThread} />}

      <nav className="border-line bg-paper fixed inset-x-0 bottom-0 border-t pb-[env(safe-area-inset-bottom)]">
        <div className="mx-auto flex w-full max-w-md">
          {TABS.map((tab) => (
            <button
              key={tab}
              onClick={() => setScreen(tab)}
              className={`flex-1 py-4 text-sm ${
                screen === tab ? "text-ink font-medium" : "text-faint"
              }`}
            >
              {tab}
            </button>
          ))}
        </div>
      </nav>
    </main>
  );
}

"use client";

import { useRef, useState } from "react";

export default function Capture({ hobby, onSave }) {
  const [imageUrl, setImageUrl] = useState(null);
  const [note, setNote] = useState("");
  const cameraRef = useRef(null);
  const libraryRef = useRef(null);

  const nextIndex = hobby.attempts.length + 1;

  function handleFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setImageUrl(URL.createObjectURL(file));
    e.target.value = "";
  }

  function save() {
    onSave({ imageUrl, note: note.trim() });
    setImageUrl(null);
    setNote("");
  }

  return (
    <section className="flex min-h-[calc(100dvh-3.5rem)] flex-col px-5 pt-8">
      <header>
        <h1 className="text-xl font-medium">{hobby.name}</h1>
        <p className="text-faint mt-1 text-sm">attempt {nextIndex}</p>
      </header>

      <input
        ref={cameraRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        onChange={handleFile}
      />
      <input
        ref={libraryRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={handleFile}
      />

      {!imageUrl ? (
        <div className="flex flex-1 flex-col justify-end pb-10">
          <button
            onClick={() => cameraRef.current?.click()}
            className="bg-ink text-paper w-full rounded-2xl py-16 text-base font-medium active:opacity-80"
          >
            take a photo
          </button>
          <button
            onClick={() => libraryRef.current?.click()}
            className="text-faint mt-4 w-full py-3 text-sm active:opacity-60"
          >
            import from library
          </button>
        </div>
      ) : (
        <div className="flex flex-1 flex-col pb-10">
          <div className="mt-7 aspect-[3/4] overflow-hidden rounded-xl bg-line">
            <img
              src={imageUrl}
              alt={`attempt ${nextIndex}`}
              className="h-full w-full object-cover"
            />
          </div>
          <input
            type="text"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="what'd you try?"
            enterKeyHint="done"
            className="placeholder:text-faint mt-5 w-full border-b border-line bg-transparent pb-2 text-base focus:border-ink focus:outline-none"
          />
          <div className="flex-1" />
          <button
            onClick={save}
            className="bg-ink text-paper mt-8 w-full rounded-2xl py-4 text-base font-medium active:opacity-80"
          >
            done
          </button>
          <button
            onClick={() => setImageUrl(null)}
            className="text-faint mt-3 w-full py-2 text-sm active:opacity-60"
          >
            retake
          </button>
        </div>
      )}
    </section>
  );
}

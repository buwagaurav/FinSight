"use client";

import { usePathname } from "next/navigation";
import GoogleButton from "./GoogleButton";

/** Shown in place of an AI feature for signed-out visitors. */
export default function SignInPrompt({ what }: { what: string }) {
  const path = usePathname();
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-surface-2/60 p-3">
      <p className="text-sm text-ink-2 flex-1 min-w-[12rem]">Sign in with Google to {what}. It&apos;s free.</p>
      <GoogleButton next={path} size="sm" label="Sign in with Google" />
    </div>
  );
}

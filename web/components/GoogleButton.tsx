"use client";

import { useFormStatus } from "react-dom";
import { signInWithGoogle } from "@/app/actions";

function GoogleG({ size }: { size: number }) {
  return (
    <svg aria-hidden="true" width={size} height={size} viewBox="0 0 48 48">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
    </svg>
  );
}

function Inner({ big, label, compact }: { big: boolean; label: string; compact: boolean }) {
  const { pending } = useFormStatus();
  const icon = big ? 20 : 16;
  return (
    <span className="group/halo relative isolate inline-flex">
    {/* soft Google-colour rim that fades in around the button on hover */}
    <span aria-hidden="true"
      className="pointer-events-none absolute -inset-[3px] -z-10 rounded-full opacity-0 blur-[6px] transition-opacity duration-300 group-hover/halo:opacity-60 bg-[conic-gradient(from_200deg,#4285F4,#34A853,#FBBC05,#EA4335,#4285F4)]" />
    <button
      type="submit"
      disabled={pending}
      aria-busy={pending}
      aria-label={compact ? label : undefined}
      className={[
        "group relative inline-flex items-center justify-center rounded-full font-medium",
        // Google's light and dark button styles
        "border border-[#dadce0] bg-white text-[#1f1f1f]",
        "dark:border-[#8e918f] dark:bg-[#131314] dark:text-[#e3e3e3]",
        "shadow-sm transition-[transform,box-shadow,border-color,background-color] duration-200 ease-out",
        // hover: lift, soft blue glow, tinted border
        "hover:border-[#4285F4]/50 hover:shadow-[0_8px_24px_-6px_rgba(66,133,244,0.45)]",
        "motion-safe:hover:-translate-y-0.5 dark:hover:bg-[#1b1c1e]",
        // press
        "active:shadow-sm motion-safe:active:translate-y-0 motion-safe:active:scale-[0.98]",
        "focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#4285F4]/35",
        "disabled:cursor-wait disabled:opacity-90",
        big ? "h-12 pl-5 pr-6 text-base gap-3" : compact ? "h-9 w-9 sm:w-auto sm:pl-3.5 sm:pr-4 text-sm gap-2.5" : "h-9 pl-3.5 pr-4 text-sm gap-2.5",
      ].join(" ")}
    >
      {pending ? (
        <span aria-hidden="true" className="animate-spin rounded-full border-2 border-[#4285F4] border-t-transparent" style={{ width: icon, height: icon }} />
      ) : (
        <span className="transition-transform duration-300 ease-out motion-safe:group-hover:scale-110 motion-safe:group-hover:-rotate-12">
          <GoogleG size={icon} />
        </span>
      )}
      <span className={compact ? "hidden sm:inline" : undefined}>{pending ? "Connecting to Google…" : label}</span>
      {!pending && (
        <span aria-hidden="true"
          className={`${compact ? "hidden sm:inline-block " : ""}-ml-1 w-0 overflow-hidden opacity-0 transition-all duration-200 ease-out group-hover:ml-0 group-hover:w-4 group-hover:opacity-100 motion-safe:group-hover:translate-x-0.5`}>
          →
        </span>
      )}
    </button>
    </span>
  );
}

/** Google-branded sign-in button: lifts with a soft glow on hover, presses in on click, shows progress while redirecting. */
export default function GoogleButton({ next = "/home", size = "lg", label = "Continue with Google", compact = false }: { next?: string; size?: "lg" | "sm"; label?: string; compact?: boolean }) {
  return (
    <form action={signInWithGoogle}>
      <input type="hidden" name="next" value={next} />
      <Inner big={size === "lg"} label={label} compact={compact} />
    </form>
  );
}

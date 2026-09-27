import NextAuth from "next-auth";
import Google from "next-auth/providers/google";

// Sign-in is on when these are set (Netlify environment / web/.env.local); otherwise the site runs without accounts.
export const authEnabled = Boolean(process.env.AUTH_SECRET && process.env.AUTH_GOOGLE_ID && process.env.AUTH_GOOGLE_SECRET);

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [Google], // reads AUTH_GOOGLE_ID and AUTH_GOOGLE_SECRET
  trustHost: true,     // required outside Vercel (Netlify, localhost)
  session: { strategy: "jwt" },
  pages: { signIn: "/" },
  callbacks: {
    // expose Google's stable account id (token.sub) so the API can key users on it rather than on email
    session({ session, token }) {
      if (token.sub && session.user) session.user.id = token.sub;
      return session;
    },
  },
});

export type SessionUser = { name: string | null; email: string | null; image: string | null };

/** The signed-in user, or null. Never throws, so pages still render if auth is misconfigured. */
export async function currentUser(): Promise<SessionUser | null> {
  if (!authEnabled) return null;
  try {
    const session = await auth();
    const u = session?.user;
    return u ? { name: u.name ?? null, email: u.email ?? null, image: u.image ?? null } : null;
  } catch {
    return null;
  }
}

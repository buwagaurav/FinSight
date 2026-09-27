import NextAuth from "next-auth";
import Google from "next-auth/providers/google";

// Sign-in is on when these are set (Netlify environment / web/.env.local); otherwise the site runs without accounts.
export const authEnabled = Boolean(process.env.AUTH_SECRET && process.env.AUTH_GOOGLE_ID && process.env.AUTH_GOOGLE_SECRET);

// Pin sign-in to the public address (see FINSIGHT_SITE_URL in next.config.ts). Auth.js reads AUTH_URL per request.
if (!process.env.AUTH_URL && process.env.FINSIGHT_SITE_URL) process.env.AUTH_URL = process.env.FINSIGHT_SITE_URL;

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [Google], // reads AUTH_GOOGLE_ID and AUTH_GOOGLE_SECRET
  trustHost: true,     // required outside Vercel (Netlify, localhost)
  session: { strategy: "jwt" },
  pages: { signIn: "/" },
  callbacks: {
    // Without a database adapter Auth.js gives every sign-in a fresh random user id (token.sub), which made each
    // sign-in look like a new person (empty watchlist, reset AI allowance). Use Google's stable account id instead.
    jwt({ token, account }) {
      if (account?.providerAccountId) token.sub = account.providerAccountId;
      return token;
    },
    // expose that id so the API keys users on it rather than on email
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

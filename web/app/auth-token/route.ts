import { SignJWT } from "jose";
import { auth, authEnabled } from "@/auth";

/**
 * A short-lived pass the browser sends to the FinSight API for AI requests. The API (a different domain) can't read
 * the website's session cookie, so it verifies this token instead, signed with FINSIGHT_API_JWT_SECRET, which only
 * the website and the API know.
 */
export async function GET() {
  const secret = process.env.FINSIGHT_API_JWT_SECRET;
  if (!authEnabled || !secret) return Response.json({ error: "Sign-in is not configured" }, { status: 503 });
  const session = await auth();
  const sub = (session?.user as { id?: string } | undefined)?.id ?? session?.user?.email;
  if (!session?.user || !sub) return Response.json({ error: "Not signed in" }, { status: 401 });

  const expiresIn = 60 * 60;
  const token = await new SignJWT({ email: session.user.email, name: session.user.name, picture: session.user.image })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(String(sub))
    .setIssuer("finsight-web")
    .setAudience("finsight-api")
    .setIssuedAt()
    .setExpirationTime(`${expiresIn}s`)
    .sign(new TextEncoder().encode(secret));
  return Response.json({ token, expires_at: Date.now() + expiresIn * 1000 }, { headers: { "Cache-Control": "no-store" } });
}

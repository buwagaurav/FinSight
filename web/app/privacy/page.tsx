import type { Metadata } from "next";
import Link from "next/link";
import LegalPage, { Contact, Section } from "@/components/LegalPage";

export const metadata: Metadata = { title: "Privacy Policy · FinSight" };

export default function Privacy() {
  return (
    <LegalPage title="Privacy Policy"
      intro="FinSight is a research tool for Indian stocks and IPOs. This page explains what personal data we collect when you use it, why, where it is stored, and the choices you have. We collect as little as we can.">
      <Section title="What we collect">
        <p>If you only browse FinSight without signing in, we don&apos;t collect personal data about you.</p>
        <p>When you sign in with Google, Google shares these details with us, and we store them:</p>
        <ul>
          <li>Your name, email address and profile picture</li>
          <li>Your Google account ID (a number that identifies your account)</li>
          <li>When you first signed in and when you were last active</li>
        </ul>
        <p>When you use the AI features, we record how many AI requests you made each day, to apply the daily allowance.</p>
        <p>We never get access to your Google password, Gmail, Drive, contacts or any other Google data.</p>
      </Section>

      <Section title="Why we use it">
        <ul>
          <li>To sign you in and keep you signed in</li>
          <li>To apply the daily AI allowance fairly and protect the service from abuse</li>
          <li>To show your name and picture in the menu</li>
          <li>To provide personal features we add later, such as watchlists</li>
        </ul>
        <p>We do not sell your data, show advertising, or use your data to profile you for marketing.</p>
      </Section>

      <Section title="What you type into the AI features">
        <p>
          Questions you ask FinSight&apos;s AI, and the company data needed to answer them, are sent to our AI provider,
          currently <strong className="text-ink">DeepSeek</strong>, a company based in China, to generate the answer.
          Your name and email are not sent with them. Please don&apos;t type personal information into questions.
        </p>
      </Section>

      <Section title="Where your data is stored">
        <ul>
          <li><strong className="text-ink">Neon</strong> (database, Singapore region): your account details and AI usage counts</li>
          <li><strong className="text-ink">Netlify</strong> (website) and <strong className="text-ink">Render</strong> (API, Singapore region), which may keep standard technical logs such as IP address and browser type</li>
          <li><strong className="text-ink">Google</strong>, which handles sign-in under its own privacy policy</li>
        </ul>
        <p>These providers process data on our behalf and may store it outside India.</p>
      </Section>

      <Section title="Cookies">
        <p>
          We use only the cookies needed for sign-in: an encrypted session cookie that keeps you signed in, plus short-lived
          cookies that protect the sign-in process. We don&apos;t use advertising or tracking cookies.
        </p>
      </Section>

      <Section title="How long we keep it">
        <p>We keep your account details and usage counts for as long as you have an account. If you ask us to delete your account, we delete them within 30 days.</p>
      </Section>

      <Section title="Your rights">
        <p>
          Under India&apos;s Digital Personal Data Protection Act, 2023, you can ask what data we hold about you, ask us to
          correct it, or ask us to delete your account and data. You can also stop using FinSight and remove its access
          from your Google account at any time (Google Account &gt; Security &gt; Third-party connections).
        </p>
        <p>To make a request, <Contact />.</p>
      </Section>

      <Section title="Children">
        <p>FinSight is meant for adults. Please don&apos;t use it if you are under 18.</p>
      </Section>

      <Section title="Changes">
        <p>If we change how we handle personal data, we will update this page and the date at the top.</p>
      </Section>

      <Section title="Contact">
        <p>Questions about privacy? <Contact />. See also our <Link href="/terms" className="text-accent underline">Terms of Use</Link>.</p>
      </Section>
    </LegalPage>
  );
}

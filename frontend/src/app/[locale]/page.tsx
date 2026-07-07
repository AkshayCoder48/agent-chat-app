import { redirect } from "next/navigation";

/**
 * Root page — redirects to the login page.
 *
 * The previous landing/marketing page (with "Start free" CTA, hero, pricing,
 * testimonials, FAQ) was removed per product decision: visitors land directly
 * on /login, where they can sign in or follow the "create account" link to
 * /register. Authenticated users hitting "/" will be bounced to /chat by the
 * login page's own redirect logic.
 */
export default function HomePage() {
  redirect("/login");
}

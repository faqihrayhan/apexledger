import { Editions } from "@/components/Editions";
import { Features } from "@/components/Features";
import { Footer } from "@/components/Footer";
import { Hero } from "@/components/Hero";
import { Install } from "@/components/Install";
import { Navbar } from "@/components/Navbar";
import { Security } from "@/components/Security";

/**
 * Landing page shell — each section lives in its own component
 * under src/components/. Content comes from messages/en.json,
 * URLs from lib/site.ts (single source of truth).
 */
export default function Home() {
  return (
    <>
      <Navbar />
      <Hero />
      <Features />
      <Security />
      <Editions />
      <Install />
      <Footer />
    </>
  );
}

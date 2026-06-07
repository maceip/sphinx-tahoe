import Hero from "./components/Hero";
import DemoLoop from "./components/DemoLoop";
import Pillars from "./components/Pillars";
import Footer from "./components/Footer";
import { scenario } from "./data/scenario";

export default function App() {
  return (
    <div className="min-h-full">
      <Hero />
      <DemoLoop scenario={scenario} />
      <Pillars />
      <Footer />
    </div>
  );
}

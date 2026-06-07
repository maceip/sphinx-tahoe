import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
// The UI POSTs to /pick. In dev we proxy that to the real Python PickServer
// (set VITE_PICK_SERVER_URL). If unset, the app uses the built-in simulation.
export default defineConfig(function (_a) {
    var mode = _a.mode;
    var env = loadEnv(mode, process.cwd(), "");
    var target = env.VITE_PICK_SERVER_URL;
    return {
        plugins: [react()],
        server: target
            ? { proxy: { "/pick": { target: target, changeOrigin: true } } }
            : {},
    };
});

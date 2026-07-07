import { redirect } from "next/navigation";
import { ROUTES } from "@/lib/constants";

// Plugins have been retired — Skills + MCPs + Custom Tools cover everything
// the plugin system used to do. Redirect any stale links to the Tools page.
export default function PluginsSettingsPage() {
  redirect(ROUTES.SETTINGS_TOOLS);
}

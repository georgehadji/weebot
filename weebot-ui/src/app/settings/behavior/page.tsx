import { redirect } from "next/navigation";

/**
 * Merged into /behavior (Monitor + Settings tabs) — see T4.4 in
 * mission_center_ui_implementation_plan.md. Kept as a redirect so old
 * bookmarks/links still land somewhere useful.
 */
export default function BehaviorSettingsRedirect() {
  redirect("/behavior?tab=settings");
}

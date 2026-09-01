import React from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { useAppState } from "@/hooks/useAppState";
import { getSettings } from "@/lib/settings";
import { fetchStatus, previewUninstall, executeUninstall } from "@/lib/api";
import { FadeIn } from "@/components/FadeIn";
import { ReportView } from "@/components/ReportView";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { setLastStatus } from "@/lib/store";

export function Manage() {
  const { t } = useTranslation();
  const { cliInfo, operationInProgress } = useAppState();
  const [managedDir, setManagedDir] = React.useState(() => getSettings().defaultManagedDir || "");
  const [status, setStatus] = React.useState(null);
  // Keep the exact options used for the preview so editing the field later
  // cannot redirect the destructive confirmation to another directory.
  const [pending, setPending] = React.useState(null);
  const [confirmOpen, setConfirmOpen] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [done, setDone] = React.useState(null);

  const options = { managedDir: managedDir.trim() };

  const reload = React.useCallback(async () => {
    if (!cliInfo.path) return;
    try {
      const next = await fetchStatus(options);
      setStatus(next);
      setLastStatus(next);
    } catch (err) {
      toast.error(err?.message || t("manage.failed"));
    }
  }, [cliInfo.path, managedDir, t]); // eslint-disable-line react-hooks/exhaustive-deps

  React.useEffect(() => { reload(); }, [reload]);

  const start = async () => {
    const previewOptions = { managedDir: managedDir.trim() };
    setBusy(true);
    try {
      const preview = await previewUninstall(previewOptions);
      setPending({ options: previewOptions, report: preview });
      setConfirmOpen(true);
    } catch (err) {
      toast.error(err?.message || t("manage.failed"));
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    if (!pending) return;
    setBusy(true);
    try {
      const report = await executeUninstall(pending.options);
      setDone(report);
      setConfirmOpen(false);
      setPending(null);
      if (report.gate.ok) toast.success(t("manage.done"));
      else toast.error(t("manage.failed"));
      await reload();
    } catch (err) {
      toast.error(err?.message || t("manage.failed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <FadeIn>
        <h1 className="text-2xl font-semibold tracking-tight">{t("manage.title")}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{t("manage.subtitle")}</p>
      </FadeIn>

      <section className="card-glass mt-6 p-5">
        <label className="text-sm font-medium" htmlFor="manage-dir">{t("manage.selectDir")}</label>
        <Input id="manage-dir" className="mt-1.5 font-mono text-xs" value={managedDir} onChange={(e) => setManagedDir(e.target.value)} />
        {status?.backups?.length > 0 && (
          <div className="mt-3 text-xs">
            <h2 className="font-medium text-muted-foreground">{t("dash.backups")}</h2>
            <ul className="mt-1 space-y-1 font-mono text-secondary-foreground">
              {status.backups.map((item, index) => (
                <li key={index} className="break-all">{item.path || item.name}</li>
              ))}
            </ul>
          </div>
        )}
        <div className="mt-4">
          <Button disabled={busy || operationInProgress || !cliInfo.path} onClick={start}>
            {t("manage.uninstall")}
          </Button>
        </div>
      </section>

      {pending && (
        <section className="card-glass mt-4 p-5">
          <h2 className="text-sm font-medium">{t("manage.previewPlan")}</h2>
          <div className="mt-3"><ReportView report={pending.report} showTarget={false} /></div>
        </section>
      )}
      {done && (
        <section className="card-glass mt-4 p-5">
          <h2 className="text-sm font-medium">{t("manage.result")}</h2>
          <div className="mt-3"><ReportView report={done} showTarget={false} /></div>
        </section>
      )}

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title={t("manage.confirmUninstall")}
        body={t("manage.uninstallDesc")}
        confirmText={t("manage.execute")}
        confirmDisabled={busy}
        danger
        onConfirm={confirm}
      />
    </div>
  );
}

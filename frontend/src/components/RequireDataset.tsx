import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Database, Loader2, Upload } from "lucide-react";
import { useDatasets } from "../lib/context";
import { Button, Card, EmptyState, Skeleton } from "./ui";

/** Shows a helpful state until a processed dataset is available for the page. */
export function RequireDataset({ children }: { children: (datasetId: string) => ReactNode }) {
  const { dataset, datasetId, datasets, loading } = useDatasets();
  if (loading && !datasets.length) return <div className="space-y-3"><Skeleton className="h-20" /><Skeleton className="h-72" /></div>;
  if (dataset && dataset.status !== "ready") {
    return <Card><EmptyState icon={Loader2} title={dataset.status === "failed" ? "This dataset could not be processed" : "This dataset is still processing"}>{dataset.status === "failed" ? dataset.error_message : "It will be available here when processing finishes."}</EmptyState></Card>;
  }
  if (!datasetId) {
    return (
      <Card>
        <EmptyState icon={Database} title="No dataset available" actions={<Link to="/datasets?upload=1"><Button variant="primary" icon={Upload} tabIndex={-1}>Upload dataset</Button></Link>}>
          Upload a dataset or load the demonstration data to use this page.
        </EmptyState>
      </Card>
    );
  }
  return <>{children(datasetId)}</>;
}

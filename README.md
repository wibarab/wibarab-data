## Re-Deploy WIBARAB Website

*  Start GitHub Workflow in the vicav-app repository https://github.com/acdh-oeaw/vicav-app:
   * choose `generate-workflow_vars-wibarab` and
   * click `re-run this job`
   * wait until it is done.
*  Go to ACDH-CH Rancher https://rancher.acdh-dev.oeaw.ac.at/dashboard/home and 
   * click on `AC2` at the upper left corner of the screen  or `acdh-ch-cluster-2`
   * then search for `vicav-test` in the window in the upper right corner of the screen
   * click on `workloads` (menu on the left) and on `deployments`
   * now choose `wibarab-app-devel` and
   * click `redeploy` (three dots on the right)
   * wait until it is done

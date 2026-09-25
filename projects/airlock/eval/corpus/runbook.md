# Production runbook

owner: Lars Olesen
company: Nordbro
host: nordbro-rmq-prd.westeurope.cloudapp.azure.com

The service uses Azure Key Vault and the App Service platform. Restart the worker
after checking the queue depth and preserve the error code for the incident review.

param tenantId string = '12345678-1234-4234-8234-123456789012'
resource app 'Microsoft.Web/sites@2022-03-01' = {
  name: 'qconv-inhouse-prd'
  location: 'westeurope'
}

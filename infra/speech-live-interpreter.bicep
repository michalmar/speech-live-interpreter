targetScope = 'resourceGroup'

@description('Globally unique Azure Speech resource and custom subdomain name.')
@minLength(2)
@maxLength(64)
param accountName string

@description('Azure region that supports Live Interpreter.')
param location string = 'eastus'

@description('Microsoft Entra principal that runs the local demo.')
param speechUserPrincipalId string

@description('Tags applied to the Speech resource.')
param tags object = {
  environment: 'demo'
  purpose: 'speech-live-interpreter'
}

var speechUserRoleDefinitionId = 'f2dc8367-1007-4938-bd23-fe263f013447'

resource speech 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accountName
  location: location
  kind: 'SpeechServices'
  sku: {
    name: 'S0'
  }
  tags: tags
  properties: {
    allowProjectManagement: false
    customSubDomainName: accountName
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
    }
  }
}

resource speechUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(speech.id, speechUserPrincipalId, speechUserRoleDefinitionId)
  scope: speech
  properties: {
    principalId: speechUserPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      speechUserRoleDefinitionId
    )
  }
}

output accountId string = speech.id
output accountName string = speech.name
output endpoint string = speech.properties.endpoint
output location string = speech.location

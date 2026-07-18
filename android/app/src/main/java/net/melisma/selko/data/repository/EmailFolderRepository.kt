package net.melisma.selko.data.repository

import net.melisma.selko.data.api.BackendApiClient
import net.melisma.selko.data.model.EmailFolderPreference
import net.melisma.selko.data.model.IntegrationProvider

open class EmailFolderRepository(private val api: BackendApiClient) {
    open suspend fun list(provider: IntegrationProvider): RepositoryResult<List<EmailFolderPreference>> {
        val key = provider.folderApiKey()
            ?: return RepositoryResult.Error("Unsupported email provider")
        return api.listEmailFolders(key).fold(
            onSuccess = { RepositoryResult.Success(it.filterNot(EmailFolderPreference::isSystem)) },
            onFailure = { RepositoryResult.Error(it.message ?: "Failed to load folders") }
        )
    }

    open suspend fun update(
        provider: IntegrationProvider,
        folderId: String,
        isIncluded: Boolean
    ): RepositoryResult<EmailFolderPreference> {
        val key = provider.folderApiKey()
            ?: return RepositoryResult.Error("Unsupported email provider")
        return api.updateEmailFolder(key, folderId, isIncluded).fold(
            onSuccess = { RepositoryResult.Success(it) },
            onFailure = { RepositoryResult.Error(it.message ?: "Failed to save folder") }
        )
    }
}

fun IntegrationProvider.folderApiKey(): String? = when (this) {
    IntegrationProvider.GMAIL -> "gmail"
    IntegrationProvider.OUTLOOK -> "outlook"
    else -> null
}

#include "CoreMinimal.h"
#include "CoreGlobals.h"
#include "Containers/Array.h"
#include "Containers/StringConv.h"
#include "Dom/JsonObject.h"
#include "HAL/CriticalSection.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformProcess.h"
#include "Misc/CoreDelegates.h"
#include "Misc/DateTime.h"
#include "Misc/FileHelper.h"
#include "Misc/Guid.h"
#include "Misc/OutputDevice.h"
#include "Misc/OutputDeviceRedirector.h"
#include "Misc/Paths.h"
#include "Modules/ModuleManager.h"
#include "Runtime/Launch/Resources/Version.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

// Global buffer for captured errors
TArray<FString> GCapturedEngineErrors;
FCriticalSection GCapturedEngineErrorsMutex;

class FCliAnythingLogHook : public FOutputDevice
{
public:
	virtual void Serialize(const TCHAR* V, ELogVerbosity::Type Verbosity, const class FName& Category) override
	{
		// We capture Errors and Warnings
		if (Verbosity == ELogVerbosity::Error || Verbosity == ELogVerbosity::Warning)
		{
			FScopeLock Lock(&GCapturedEngineErrorsMutex);

			bool bIsGameThread = IsInGameThread();

			FString Msg = FString::Printf(TEXT("[%s] %s: %s (IsGameThread: %s)"), *Category.ToString(),
				(Verbosity == ELogVerbosity::Error) ? TEXT("Error") : TEXT("Warning"), V,
				bIsGameThread ? TEXT("True") : TEXT("False"));

			GCapturedEngineErrors.Add(Msg);

			// Keep only the last 500 errors to avoid unbounded memory growth
			if (GCapturedEngineErrors.Num() > 500)
			{
#if ENGINE_MAJOR_VERSION >= 5
				GCapturedEngineErrors.RemoveAt(0, GCapturedEngineErrors.Num() - 500, EAllowShrinking::No);
#else
				GCapturedEngineErrors.RemoveAt(0, GCapturedEngineErrors.Num() - 500, false);
#endif
			}
		}
	}
};

static FCliAnythingLogHook* GLogHook = nullptr;
#define CLI_ANYTHING_HAS_CATEGORIZED_MODAL_DIALOG \
	(ENGINE_MAJOR_VERSION > 5 || (ENGINE_MAJOR_VERSION == 5 && ENGINE_MINOR_VERSION >= 3))

static bool GDialogHookInstalled = false;
static FDelegateHandle GDialogHookHandle;

#if CLI_ANYTHING_HAS_CATEGORIZED_MODAL_DIALOG
static decltype(FCoreDelegates::ModalMessageDialog) GOriginalModalMessageDialog;
#else
static decltype(FCoreDelegates::ModalErrorMessage) GOriginalModalMessageDialog;
#endif

static FString GetConfirmationDirectory()
{
	return FPaths::Combine(
		FPaths::ProjectSavedDir(),
		TEXT("CliAnything"),
		TEXT("Confirmations"),
		FString::FromInt(static_cast<int32>(FPlatformProcess::GetCurrentProcessId())));
}

static bool LoadJsonFile(const FString& Path, TSharedPtr<FJsonObject>& OutObject)
{
	FString Json;
	if (!FFileHelper::LoadFileToString(Json, *Path)) return false;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Json);
	return FJsonSerializer::Deserialize(Reader, OutObject) && OutObject.IsValid();
}

static bool SaveJsonFileAtomic(const FString& Path, const TSharedRef<FJsonObject>& Object)
{
	FString Json;
	const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Json);
	if (!FJsonSerializer::Serialize(Object, Writer, false)) return false;
	Writer->Close();

	IFileManager& FileManager = IFileManager::Get();
	if (!FileManager.MakeDirectory(*FPaths::GetPath(Path), true)) return false;
	const FString TempPath = Path + TEXT(".") + FGuid::NewGuid().ToString(EGuidFormats::Digits) + TEXT(".tmp");
	if (!FFileHelper::SaveStringToFile(
		Json,
		*TempPath,
		FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM))
	{
		return false;
	}
	if (!FileManager.Move(*Path, *TempPath, true, true))
	{
		FileManager.Delete(*TempPath, false, true);
		return false;
	}
	return true;
}

static bool IsConfirmationBrokerEnabled(int64& OutExpiresAt)
{
	TSharedPtr<FJsonObject> Lease;
	if (!LoadJsonFile(FPaths::Combine(GetConfirmationDirectory(), TEXT("lease.json")), Lease)) return false;

	bool bEnabled = false;
	double LeasePid = 0.0;
	double ExpiresAt = 0.0;
	if (!Lease->TryGetBoolField(TEXT("enabled"), bEnabled)
		|| !Lease->TryGetNumberField(TEXT("pid"), LeasePid)
		|| !Lease->TryGetNumberField(TEXT("expires_at"), ExpiresAt))
	{
		return false;
	}
	OutExpiresAt = static_cast<int64>(ExpiresAt);
	return bEnabled
		&& static_cast<uint32>(LeasePid) == FPlatformProcess::GetCurrentProcessId()
		&& OutExpiresAt > FDateTime::UtcNow().ToUnixTimestamp();
}

static FString MessageTypeToString(EAppMsgType::Type MessageType)
{
	switch (MessageType)
	{
	case EAppMsgType::Ok: return TEXT("ok");
	case EAppMsgType::YesNo: return TEXT("yes_no");
	case EAppMsgType::OkCancel: return TEXT("ok_cancel");
	case EAppMsgType::YesNoCancel: return TEXT("yes_no_cancel");
	case EAppMsgType::CancelRetryContinue: return TEXT("cancel_retry_continue");
	case EAppMsgType::YesNoYesAllNoAll: return TEXT("yes_no_yes_all_no_all");
	case EAppMsgType::YesNoYesAllNoAllCancel: return TEXT("yes_no_yes_all_no_all_cancel");
	case EAppMsgType::YesNoYesAll: return TEXT("yes_no_yes_all");
	default: return TEXT("unknown");
	}
}

static TArray<FString> ChoicesForMessageType(EAppMsgType::Type MessageType)
{
	switch (MessageType)
	{
	case EAppMsgType::Ok: return {TEXT("ok")};
	case EAppMsgType::YesNo: return {TEXT("yes"), TEXT("no")};
	case EAppMsgType::OkCancel: return {TEXT("ok"), TEXT("cancel")};
	case EAppMsgType::YesNoCancel: return {TEXT("yes"), TEXT("no"), TEXT("cancel")};
	case EAppMsgType::CancelRetryContinue: return {TEXT("cancel"), TEXT("retry"), TEXT("continue")};
	case EAppMsgType::YesNoYesAllNoAll: return {TEXT("yes"), TEXT("no"), TEXT("yes_all"), TEXT("no_all")};
	case EAppMsgType::YesNoYesAllNoAllCancel: return {TEXT("yes"), TEXT("no"), TEXT("yes_all"), TEXT("no_all"), TEXT("cancel")};
	case EAppMsgType::YesNoYesAll: return {TEXT("yes"), TEXT("no"), TEXT("yes_all")};
	default: return {};
	}
}

static EAppReturnType::Type SafeDefaultForMessageType(EAppMsgType::Type MessageType)
{
	switch (MessageType)
	{
	case EAppMsgType::Ok: return EAppReturnType::Ok;
	case EAppMsgType::YesNo: return EAppReturnType::No;
	case EAppMsgType::OkCancel: return EAppReturnType::Cancel;
	case EAppMsgType::YesNoCancel: return EAppReturnType::Cancel;
	case EAppMsgType::CancelRetryContinue: return EAppReturnType::Cancel;
	case EAppMsgType::YesNoYesAllNoAll: return EAppReturnType::No;
	case EAppMsgType::YesNoYesAllNoAllCancel: return EAppReturnType::Cancel;
	case EAppMsgType::YesNoYesAll: return EAppReturnType::No;
	default: return EAppReturnType::Cancel;
	}
}

static FString ReturnTypeToChoice(EAppReturnType::Type ReturnType)
{
	switch (ReturnType)
	{
	case EAppReturnType::No: return TEXT("no");
	case EAppReturnType::Yes: return TEXT("yes");
	case EAppReturnType::YesAll: return TEXT("yes_all");
	case EAppReturnType::NoAll: return TEXT("no_all");
	case EAppReturnType::Cancel: return TEXT("cancel");
	case EAppReturnType::Ok: return TEXT("ok");
	case EAppReturnType::Retry: return TEXT("retry");
	case EAppReturnType::Continue: return TEXT("continue");
	default: return TEXT("cancel");
	}
}

static bool ChoiceToReturnType(const FString& Choice, EAppReturnType::Type& OutReturnType)
{
	if (Choice == TEXT("no")) OutReturnType = EAppReturnType::No;
	else if (Choice == TEXT("yes")) OutReturnType = EAppReturnType::Yes;
	else if (Choice == TEXT("yes_all")) OutReturnType = EAppReturnType::YesAll;
	else if (Choice == TEXT("no_all")) OutReturnType = EAppReturnType::NoAll;
	else if (Choice == TEXT("cancel")) OutReturnType = EAppReturnType::Cancel;
	else if (Choice == TEXT("ok")) OutReturnType = EAppReturnType::Ok;
	else if (Choice == TEXT("retry")) OutReturnType = EAppReturnType::Retry;
	else if (Choice == TEXT("continue")) OutReturnType = EAppReturnType::Continue;
	else return false;
	return true;
}

#if CLI_ANYTHING_HAS_CATEGORIZED_MODAL_DIALOG
static FString MessageCategoryToString(EAppMsgCategory Category)
{
	switch (Category)
	{
	case EAppMsgCategory::Warning: return TEXT("warning");
	case EAppMsgCategory::Error: return TEXT("error");
	case EAppMsgCategory::Success: return TEXT("success");
	case EAppMsgCategory::Info: return TEXT("info");
	default: return TEXT("unknown");
	}
}
#endif

static bool TryReadConfirmationResponse(
	const FString& ResponsePath,
	const FString& ConfirmationId,
	const TArray<FString>& Choices,
	EAppReturnType::Type& OutReturnType)
{
	TSharedPtr<FJsonObject> Response;
	if (!LoadJsonFile(ResponsePath, Response)) return false;

	FString ResponseId;
	FString Choice;
	const bool bValid = Response->TryGetStringField(TEXT("confirmation_id"), ResponseId)
		&& Response->TryGetStringField(TEXT("choice"), Choice)
		&& ResponseId == ConfirmationId
		&& Choices.Contains(Choice)
		&& ChoiceToReturnType(Choice, OutReturnType);
	if (!bValid)
	{
		IFileManager::Get().Delete(*ResponsePath, false, true);
	}
	return bValid;
}

#if CLI_ANYTHING_HAS_CATEGORIZED_MODAL_DIALOG
static EAppReturnType::Type CallOriginalDialog(
	EAppMsgCategory Category,
	EAppMsgType::Type MessageType,
	const FText& Message,
	const FText& Title)
{
	if (GOriginalModalMessageDialog.IsBound())
	{
		return GOriginalModalMessageDialog.Execute(Category, MessageType, Message, Title);
	}
	return FPlatformMisc::MessageBoxExt(MessageType, *Message.ToString(), *Title.ToString());
}
#else
static EAppReturnType::Type CallOriginalDialog(
	EAppMsgType::Type MessageType,
	const FText& Message,
	const FText& Title)
{
	if (GOriginalModalMessageDialog.IsBound())
	{
		return GOriginalModalMessageDialog.Execute(MessageType, Message, Title);
	}
	return FPlatformMisc::MessageBoxExt(MessageType, *Message.ToString(), *Title.ToString());
}
#endif

#if CLI_ANYTHING_HAS_CATEGORIZED_MODAL_DIALOG
static EAppReturnType::Type HandleModalMessageDialog(
	EAppMsgCategory Category,
	EAppMsgType::Type MessageType,
	const FText& Message,
	const FText& Title)
#else
static EAppReturnType::Type HandleModalMessageDialog(
	EAppMsgType::Type MessageType,
	const FText& Message,
	const FText& Title)
#endif
{
	int64 LeaseExpiresAt = 0;
	if (!IsConfirmationBrokerEnabled(LeaseExpiresAt))
	{
#if CLI_ANYTHING_HAS_CATEGORIZED_MODAL_DIALOG
		return CallOriginalDialog(Category, MessageType, Message, Title);
#else
		return CallOriginalDialog(MessageType, Message, Title);
#endif
	}

	const FString ConfirmationId = FGuid::NewGuid().ToString(EGuidFormats::Digits);
	const TArray<FString> Choices = ChoicesForMessageType(MessageType);
	if (Choices.Num() == 0)
	{
#if CLI_ANYTHING_HAS_CATEGORIZED_MODAL_DIALOG
		return CallOriginalDialog(Category, MessageType, Message, Title);
#else
		return CallOriginalDialog(MessageType, Message, Title);
#endif
	}

	TArray<TSharedPtr<FJsonValue>> JsonChoices;
	for (const FString& Choice : Choices)
	{
		JsonChoices.Add(MakeShared<FJsonValueString>(Choice));
	}
	const uint32 ProcessId = FPlatformProcess::GetCurrentProcessId();
	const TSharedRef<FJsonObject> Pending = MakeShared<FJsonObject>();
	Pending->SetNumberField(TEXT("protocol_version"), 1);
	Pending->SetStringField(TEXT("id"), ConfirmationId);
	Pending->SetNumberField(TEXT("pid"), static_cast<double>(ProcessId));
	Pending->SetStringField(TEXT("title"), Title.ToString());
	Pending->SetStringField(TEXT("message"), Message.ToString());
	Pending->SetStringField(TEXT("message_type"), MessageTypeToString(MessageType));
	Pending->SetArrayField(TEXT("choices"), JsonChoices);
	Pending->SetStringField(TEXT("safe_default"), ReturnTypeToChoice(SafeDefaultForMessageType(MessageType)));
	Pending->SetNumberField(TEXT("created_at"), static_cast<double>(FDateTime::UtcNow().ToUnixTimestamp()));
	Pending->SetNumberField(TEXT("lease_expires_at"), static_cast<double>(LeaseExpiresAt));
#if CLI_ANYTHING_HAS_CATEGORIZED_MODAL_DIALOG
	Pending->SetStringField(TEXT("category"), MessageCategoryToString(Category));
#else
	Pending->SetStringField(TEXT("category"), TEXT("unknown"));
#endif

	const FString Directory = GetConfirmationDirectory();
	const FString PendingPath = FPaths::Combine(Directory, TEXT("pending-") + ConfirmationId + TEXT(".json"));
	const FString ResponsePath = FPaths::Combine(Directory, TEXT("response-") + ConfirmationId + TEXT(".json"));
	if (!SaveJsonFileAtomic(PendingPath, Pending))
	{
#if CLI_ANYTHING_HAS_CATEGORIZED_MODAL_DIALOG
		return CallOriginalDialog(Category, MessageType, Message, Title);
#else
		return CallOriginalDialog(MessageType, Message, Title);
#endif
	}

	while (!IsEngineExitRequested())
	{
		EAppReturnType::Type Answer = SafeDefaultForMessageType(MessageType);
		if (TryReadConfirmationResponse(ResponsePath, ConfirmationId, Choices, Answer))
		{
			IFileManager::Get().Delete(*ResponsePath, false, true);
			IFileManager::Get().Delete(*PendingPath, false, true);
			return Answer;
		}
		if (!IsConfirmationBrokerEnabled(LeaseExpiresAt))
		{
			IFileManager::Get().Delete(*ResponsePath, false, true);
			IFileManager::Get().Delete(*PendingPath, false, true);
#if CLI_ANYTHING_HAS_CATEGORIZED_MODAL_DIALOG
			return CallOriginalDialog(Category, MessageType, Message, Title);
#else
			return CallOriginalDialog(MessageType, Message, Title);
#endif
		}
		FPlatformProcess::Sleep(0.05f);
	}

	IFileManager::Get().Delete(*ResponsePath, false, true);
	IFileManager::Get().Delete(*PendingPath, false, true);
	return SafeDefaultForMessageType(MessageType);
}

static void InstallDialogHook()
{
#if CLI_ANYTHING_HAS_CATEGORIZED_MODAL_DIALOG
	if (GDialogHookInstalled
		&& FCoreDelegates::ModalMessageDialog.GetHandle() == GDialogHookHandle)
	{
		return;
	}
	if (!FCoreDelegates::ModalMessageDialog.IsBound()) return;
	GOriginalModalMessageDialog = FCoreDelegates::ModalMessageDialog;
	FCoreDelegates::ModalMessageDialog.BindStatic(&HandleModalMessageDialog);
	GDialogHookHandle = FCoreDelegates::ModalMessageDialog.GetHandle();
#else
	if (GDialogHookInstalled
		&& FCoreDelegates::ModalErrorMessage.GetHandle() == GDialogHookHandle)
	{
		return;
	}
	if (!FCoreDelegates::ModalErrorMessage.IsBound()) return;
	GOriginalModalMessageDialog = FCoreDelegates::ModalErrorMessage;
	FCoreDelegates::ModalErrorMessage.BindStatic(&HandleModalMessageDialog);
	GDialogHookHandle = FCoreDelegates::ModalErrorMessage.GetHandle();
#endif
	GDialogHookInstalled = true;
}

static void UninstallDialogHook()
{
	if (!GDialogHookInstalled) return;
#if CLI_ANYTHING_HAS_CATEGORIZED_MODAL_DIALOG
	if (FCoreDelegates::ModalMessageDialog.GetHandle() == GDialogHookHandle)
	{
		FCoreDelegates::ModalMessageDialog = GOriginalModalMessageDialog;
	}
#else
	if (FCoreDelegates::ModalErrorMessage.GetHandle() == GDialogHookHandle)
	{
		FCoreDelegates::ModalErrorMessage = GOriginalModalMessageDialog;
	}
#endif
	GDialogHookInstalled = false;
	GDialogHookHandle.Reset();
}

class FCliAnythingBridgeModule : public IModuleInterface
{
public:
	virtual void StartupModule() override
	{
		GLogHook = new FCliAnythingLogHook();
		if (GLog != nullptr)
		{
			GLog->AddOutputDevice(GLogHook);
		}

#if CLI_ANYTHING_HAS_CATEGORIZED_MODAL_DIALOG
		const bool bEditorDialogBound = FCoreDelegates::ModalMessageDialog.IsBound();
#else
		const bool bEditorDialogBound = FCoreDelegates::ModalErrorMessage.IsBound();
#endif
		PostEngineInitHandle = FCoreDelegates::OnPostEngineInit.AddStatic(&InstallDialogHook);
		if (bEditorDialogBound)
		{
			InstallDialogHook();
		}
	}

	virtual void ShutdownModule() override
	{
		if (PostEngineInitHandle.IsValid())
		{
			FCoreDelegates::OnPostEngineInit.Remove(PostEngineInitHandle);
			PostEngineInitHandle.Reset();
		}
		UninstallDialogHook();
		if (GLog != nullptr && GLogHook != nullptr)
		{
			GLog->RemoveOutputDevice(GLogHook);
		}
		delete GLogHook;
		GLogHook = nullptr;
	}

private:
	FDelegateHandle PostEngineInitHandle;
};

IMPLEMENT_MODULE(FCliAnythingBridgeModule, CliAnythingBridge)

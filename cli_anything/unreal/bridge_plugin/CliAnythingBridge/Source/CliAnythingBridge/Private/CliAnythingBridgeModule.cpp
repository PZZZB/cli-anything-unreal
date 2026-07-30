#include "CoreMinimal.h"
#include "Modules/ModuleManager.h"
#include "Misc/OutputDevice.h"
#include "Misc/OutputDeviceRedirector.h"
#include "Containers/Array.h"
#include "Containers/StringConv.h"
#include "HAL/CriticalSection.h"
#include "Runtime/Launch/Resources/Version.h"

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
	}
	virtual void ShutdownModule() override
	{
		if (GLog != nullptr && GLogHook != nullptr)
		{
			GLog->RemoveOutputDevice(GLogHook);
		}
		delete GLogHook;
		GLogHook = nullptr;
	}
};

IMPLEMENT_MODULE(FCliAnythingBridgeModule, CliAnythingBridge)

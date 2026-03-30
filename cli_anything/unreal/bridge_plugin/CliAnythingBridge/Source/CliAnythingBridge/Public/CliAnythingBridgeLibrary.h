#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "CliAnythingBridgeLibrary.generated.h"

UCLASS()
class CLIANYTHINGBRIDGE_API UCliAnythingBridgeLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	/**
	 * Returns the current compile errors for a material, directly from
	 * FMaterialResource::GetCompileErrors(). Unlike log-based approaches,
	 * this reflects the exact current state regardless of shader cache.
	 */
	UFUNCTION(BlueprintCallable, Category = "CliAnything")
	static TArray<FString> GetMaterialCompileErrors(UMaterialInterface* Material);
};

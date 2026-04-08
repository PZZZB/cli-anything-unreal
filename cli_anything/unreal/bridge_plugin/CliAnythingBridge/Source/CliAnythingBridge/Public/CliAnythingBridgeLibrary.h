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

	/**
	 * Gets the absolute screen coordinates (X, Y, Width, Height) of the active level viewport.
	 * If no viewport is active or found, returns all zeros.
	 * Allows Python scripts to crop a full-screen screenshot to just the viewport.
	 */
	UFUNCTION(BlueprintCallable, Category = "CliAnything")
	static FIntVector4 GetActiveViewportScreenBounds();
};

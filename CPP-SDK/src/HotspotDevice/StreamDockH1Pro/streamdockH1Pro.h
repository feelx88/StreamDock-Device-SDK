#pragma once
#include "DeviceInfo/streamdock.h"
#include "DeviceInfo/streamdockfactory.h"

class StreamDockH1Pro : public StreamDock
{
public:
	enum class Mode : uint8_t { Screensaver = 0, Keys = 1, Gif = 2 };

	explicit StreamDockH1Pro(const hid_device_info& device_info);
	RegisterEvent dispatchEvent(uint8_t readValue, uint8_t eventValue) override;

	void switchMode(Mode mode);
	TransportResult uploadMp4Stream(const std::string& mp4Data, uint32_t timeoutMs = 20000);
	TransportResult uploadMp4File(const std::string& filePath, uint32_t timeoutMs = 20000);
	/**
	 * @brief Convert and upload a GIF without changing the current mode.
	 * @note ffmpeg must be available on PATH (the process environment variable).
	 * @note After upload, the device restarts and enumerates again over USB.
	 *       Use the newly opened device handle before switching to GIF mode.
	 */
	TransportResult uploadGifFile(const std::string& filePath, uint32_t timeoutMs = 20000);

private:
	static bool registered_H1Pro;
	static bool registered_H1ProE;
};

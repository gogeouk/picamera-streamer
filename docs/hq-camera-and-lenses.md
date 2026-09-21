# Upgrading Valleycam: the HQ camera and choosing a lens

Written 21 September 2026, for when the time comes. **Do the free fixes first**
(bottom of this page) and judge the picture again before buying anything.

## What limits the picture today

Valleycam is a Raspberry Pi 3 Model B with a **Camera Module 3** (Sony IMX708,
4608×2592, standard lens: 4.74 mm, 66°×41° field of view). Its picture has
visibly worsened since mid-2024: a green-yellow cast, haze, low contrast and grain.

| Factor | Effect | Fix |
|---|---|---|
| **Dirty housing window** | Haze, cast, low contrast, a yellow blob mid-sky | Clean it — free, and probably the biggest single gain |
| **HDR mode** | On this sensor HDR only runs 2×2-binned (2304×1296), with more grain and a flatter, more processed look | John prefers HDR, so it stays |
| **1280×720 output** | 0.9 MP out of a 12 MP sensor | 1920×1080 is possible on the current camera; see below |
| **The privacy crop** | Costs framing, not sharpness: `ScalerCrop (0,0,4008,2250)` keeps the top-left 87% each way, about 59°×36° | — |

The crop is not what makes the picture soft. Even with HDR's binning, the cropped
area still holds about 2000×1125 sensor pixels for a 1280×720 output, 1.6× more than
it needs.

## The HQ camera

Sony IMX477: **4056×3040**, 1.55 µm pixels, sensor **6.287×4.712 mm (7.9 mm
diagonal, "1/2.3-inch")**. Works with a Pi 3. Two versions, which take different
lenses ([Raspberry Pi documentation](https://www.raspberrypi.com/documentation/accessories/camera.html)):

| | **C/CS-mount** | **M12-mount** |
|---|---|---|
| Lenses | Large; includes varifocal "zoom" lenses | Small, cheap; mostly fixed focal length |
| Official lenses | 6 mm CS: 55°×45° · 16 mm C: 22.2°×16.7° | 8 mm: 49°×36° · 25 mm: 14.4°×10.9° · fisheye |
| Body + lens size | Bulky — **check it fits the housing** | Compact |
| Infrared filter | Built in (Hoya CM500) | Built in |

**"S-mount" and "M12" are the same thing**: an M12×0.5 screw thread, and S-mount is
its trade name. So the real choice is C/CS versus M12, which means lens size and
choice against housing space.

C-mount lenses fit the CS version with the 5 mm adapter ring that comes with it.
M12 lenses must be rated for a **1/2.3-inch sensor or larger**, or the corners go
dark; the M12 camera accepts back-focus lengths of 2.6–11.8 mm
([M12 variant](https://thepihut.com/products/raspberry-pi-m12-mount-high-quality-camera-module)).

## Which focal length

The horizontal field of view on the HQ sensor is `2 × atan(6.287 / (2 × f))`.

| Focal length | Horizontal × vertical at 16:9 | Compared with today |
|---|---|---|
| 5 mm | 64° × 38° | wider than today's cropped view |
| **5.5–6 mm** | **59–55° × 35–33°** | **about today's framing, with no crop needed** |
| 8 mm | 43° × 25° | noticeably tighter |
| 12 mm | 29° × 17° | the town, not the valley |

At 6 mm the full sensor width is in use: 4056 pixels across, plenty for 1080p and
headroom for more. The garden is excluded by **aiming** the camera, so no pixels are
thrown away.

## The zoom question

A varifocal lens set once and locked is **not** a waste; it is exactly how CCTV
lenses are meant to be used. You frame precisely on site (excluding the garden
optically), tighten the locking screws and leave it. What to watch for:

- **Sensor format.** Many cheap CCTV varifocals are made for 1/3-inch sensors and
  will vignette on the HQ camera. Look for **1/2-inch or larger**.
- **Resolution rating.** Look for "5 MP" or better.
- **Range.** It needs to include about **5–6 mm**; something like 4–12 mm or 5–50 mm.
- **Sharpness.** Varifocals are usually softer than a good fixed lens at the same
  focal length.
- **Drift.** Heat and vibration can move zoom and focus; lock the screws firmly.
- **Aperture.** Set it around f/4–f/5.6 for daytime sharpness, not wide open. You
  cannot change it remotely.

## The HDR catch

**The IMX477 has no built-in HDR mode.** The Camera Module 3's HDR is what gives
Valleycam the vivid look John prefers. On a Pi 3 there is no software substitute. An
HQ camera would give a cleaner, sharper, less noisy picture, but a less "punchy" one
on high-contrast days: bright sky over a dark valley.

## Recommendation

1. **Clean the window**, fix the power supply, and let the camera run for a week.
2. **Try 1080p on the current camera** (below).
3. If you still want the HQ camera: the **M12 version plus two cheap fixed lenses
   around 6 mm and 8 mm**, rated 1/2.3-inch or larger and 12 MP, is the low-risk
   route. Try both on site and keep the better. Choose C/CS plus a 1/2-inch varifocal
   only if the housing has room and you want to adjust the framing in the field.
4. Show John a side-by-side on a high-contrast day before committing, because of
   the HDR point.

## 1080p on the current camera

With HDR on, the sensor works at 2304×1296, and after the crop there are about
2000×1125 pixels, just above 1920×1080, so 1080p would use nearly all the real detail.
Costs: frames about 2.2× larger in the archive (roughly +100 GB a year for this camera
at today's rates), bigger daily videos, and more work for a Pi 3 that already
struggles for power.

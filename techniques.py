import os
import json
import re
import cv2
import numpy as np
import pytz
from multiprocessing import Pool, cpu_count
from multiprocessing.pool import ThreadPool
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
import glob
import os
import json
from datetime import datetime
import pytz
import shutil
from collections import defaultdict
from pathlib import Path
from multiprocessing.pool import ThreadPool
from functools import partial
import sys
import time


DEV_PATH = r'C:\xampp\htdocs\harvcore\harvox\invharv\usersdata\developers'
DEV_USERS = r'C:\xampp\htdocs\harvcore\harvox\invharv\usersdata\developers\developers.json'
DEFAULT_ACCOUNTMANAGEMENT = r"C:\xampp\htdocs\harvcore\harvox\invharv\default_accountmanagement.json"
INVESTOR_USERS = r"C:\xampp\htdocs\harvcore\harvox\invharv\usersdata\investors\investors.json"
INV_PATH = r"C:\xampp\htdocs\harvcore\harvox\invharv\usersdata\investors"
VERIFIED_INVESTORS = r"C:\xampp\htdocs\harvcore\harvox\invharv\verified_investors.json"
FETCHED_INVESTORS = r"C:\xampp\htdocs\harvcore\harvox\invharv\fetched_investors.json"


def load_developers_dictionary():
    """Load developers dictionary with user IDs as keys."""
    if not os.path.exists(DEV_USERS):
        print(f"Error: File not found at {DEV_USERS}")
        return {}
    try:
        with open(DEV_USERS, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: {DEV_USERS} contains invalid JSON: {e}")
        return {}
    except Exception as e:
        print(f"Error loading developers dictionary: {e}")
        return {}

def get_account_management(user_id):
    """
    Get account management configuration from the user's JSON entry.
    Uses user ID to look up the configuration.
    """
    dev_dict = load_developers_dictionary()
    user_config = dev_dict.get(str(user_id))
    if not user_config:
        return None
    return user_config.get("accountmanagement", {})

def get_analysis_paths(
    user_id,
    sym,
    tf,
    direction,
    bars,
    output_filename_base,
    receiver_tf=None,
    target=None
):
    """
    Get analysis paths for a specific user.
    User ID is the key in developers.json.
    Path structure: DEV_PATH/{user_id}/ohlc/ for source
                   DEV_PATH/{user_id}/ for output
    """
    # Root paths
    user_root = os.path.join(DEV_PATH, str(user_id))
    ohlc_source_root = os.path.join(user_root, "ohlc")
    output_root = user_root  # Output goes directly to user root
    
    # Source paths (from ohlc folder)
    source_json = os.path.join(ohlc_source_root, sym, tf, "candlesdetails", f"{direction}_{bars}.json")
    source_chart = os.path.join(ohlc_source_root, sym, tf, f"chart_{bars}.png")
    full_bars_source = os.path.join(ohlc_source_root, sym, tf, "candlesdetails", "newest_oldest.json")
    
    # Source ticks path
    source_ticks = os.path.join(ohlc_source_root, sym, f"{sym}_ticks.json")
    
    # Destination paths (directly in user root)
    dest_ticks_dir = os.path.join(output_root, sym)
    dest_ticks = os.path.join(dest_ticks_dir, f"{sym}_ticks.json")
    
    # Output directory (tf specific)
    output_dir = os.path.join(output_root, sym, tf)
    output_json = os.path.join(output_dir, output_filename_base)
    output_chart = os.path.join(output_dir, output_filename_base.replace(".json", ".png"))
    config_json = os.path.join(output_dir, "config.json")
    
    comm_paths = {}
    if receiver_tf and target:
        base_name = output_filename_base.replace(".json", "")
        comm_filename_base = f"{receiver_tf}_{base_name}_{target}_{tf}"
        comm_paths = {
            "json": os.path.join(output_dir, f"{comm_filename_base}.json"),
            "png": os.path.join(output_dir, f"{comm_filename_base}.png"),
            "base_name": comm_filename_base
        }
    
    return {
        "user_root": user_root,
        "ohlc_source_root": ohlc_source_root,
        "output_root": output_root,
        "source_json": source_json,
        "source_chart": source_chart,
        "source_ticks": source_ticks,
        "dest_ticks": dest_ticks,
        "full_bars_source": full_bars_source,
        "output_dir": output_dir,
        "output_json": output_json,
        "output_chart": output_chart,
        "config_json": config_json,
        "comm_paths": comm_paths
    }

def copy_full_candle_data(user_id):
    """
    Iterates through all symbols and timeframes, copies newest_oldest.json 
    to the developer output directory, and renames it to full_candles_data.json.
    """
    lagos_tz = pytz.timezone('Africa/Lagos')
    
    def log(msg, level="INFO"):
        ts = datetime.now(lagos_tz).strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{ts}] [{level}] {msg}")

    # 1. Load user config
    dev_dict = load_developers_dictionary()
    cfg = dev_dict.get(str(user_id))
    if not cfg:
        return f"[User {user_id}] Error: User not in dictionary."
    
    # 2. Define paths using new structure
    user_root = os.path.join(DEV_PATH, str(user_id))
    ohlc_source_root = os.path.join(user_root, "ohlc")
    output_root = user_root  # Output goes directly to user root
    
    # 3. Check if source exists
    if not os.path.exists(ohlc_source_root):
        return f"Error: OHLC source folder {ohlc_source_root} does not exist."
    
    log(f"--- STARTING FULL CANDLE DATA: User {user_id} ---")
    
    processed_count = 0
    error_count = 0

    # 4. Iterate through Symbols
    for sym in sorted(os.listdir(ohlc_source_root)):
        sym_p = os.path.join(ohlc_source_root, sym)
        if not os.path.isdir(sym_p):
            continue
            
        # 5. Iterate through Timeframes
        for tf in sorted(os.listdir(sym_p)):
            tf_p = os.path.join(sym_p, tf)
            if not os.path.isdir(tf_p):
                continue
            
            # Source: user/{id}/ohlc/SYM/TF/candlesdetails/newest_oldest.json
            source_path = os.path.join(tf_p, "candlesdetails", "newest_oldest.json")
            
            # Destination: user/{id}/SYM/TF/full_candles_data.json
            dest_dir = os.path.join(output_root, sym, tf)
            dest_path = os.path.join(dest_dir, "full_candles_data.json")

            try:
                if os.path.exists(source_path):
                    os.makedirs(dest_dir, exist_ok=True)
                    shutil.copy2(source_path, dest_path)
                    processed_count += 1
                else:
                    # Check if new_old_500.json exists as fallback
                    alt_source_path = os.path.join(tf_p, "candlesdetails", "new_old_500.json")
                    if os.path.exists(alt_source_path):
                        os.makedirs(dest_dir, exist_ok=True)
                        shutil.copy2(alt_source_path, dest_path)
                        processed_count += 1
            except Exception as e:
                log(f"Error copying {sym}/{tf}: {e}", "ERROR")
                error_count += 1

    return f"Copy Done. Files: {processed_count}, Errors: {error_count}"

def label_objects_and_text(
    img,
    cx,
    y_rect,
    h_rect,
    fvg_swing_type=None,                 
    custom_text=None,           
    object_type="arrow",        
    is_bullish_arrow=True,      
    is_marked=False,
    double_arrow=False,
    arrow_color=(0, 255, 0),
    object_color=(0, 255, 0),
    font_scale=0.55,
    text_thickness=2,
    label_position="auto",
    end_x=None,
    box_w=None,          # External function provides this
    box_h=None,          # External function provides this
    box_alpha=0.3        # Transparency threshold
):
    color = object_color if object_color != (0, 255, 0) else arrow_color

    # Dimensions for markers
    shaft_length = 26
    head_size = 9
    thickness = 2
    wing_size = 7 if double_arrow else 6

    # 1. Determine Vertical Placement (Anchor Point)
    if label_position == "auto":
        place_at_high = not is_bullish_arrow  # HH/LH → top, ll/LL → bottom
    else:
        place_at_high = (label_position.lower() == "high")

    # tip_y is the exact pixel of the wick tip (top or bottom)
    tip_y = y_rect if place_at_high else (y_rect + h_rect)

    # 2. Draw Objects (Arrows/Shapes/Lines) ONLY if is_marked is True
    if is_marked:
        if object_type in ["arrow", "reverse_arrow"]:
            def draw_single_arrow_logic(center_x: int, is_reverse=False):
                if not is_reverse:
                    if place_at_high: # Tip at top, shaft goes UP
                        shaft_start_y = tip_y - head_size
                        cv2.line(img, (center_x, shaft_start_y), (center_x, shaft_start_y - shaft_length), arrow_color, thickness)
                        pts = np.array([[center_x, tip_y - 2], [center_x - wing_size, tip_y - head_size], [center_x + wing_size, tip_y - head_size]], np.int32)
                    else: # Tip at bottom, shaft goes DOWN
                        shaft_start_y = tip_y + head_size
                        cv2.line(img, (center_x, shaft_start_y), (center_x, shaft_start_y + shaft_length), arrow_color, thickness)
                        pts = np.array([[center_x, tip_y + 2], [center_x - wing_size, tip_y + head_size], [center_x + wing_size, tip_y + head_size]], np.int32)
                else:
                    base_y = tip_y - 5 if place_at_high else tip_y + 5
                    end_y = base_y - shaft_length if place_at_high else base_y + shaft_length
                    cv2.line(img, (center_x, base_y), (center_x, end_y), arrow_color, thickness)
                    tip_offset = -head_size if place_at_high else head_size
                    pts = np.array([[center_x, end_y + tip_offset], [center_x - wing_size, end_y], [center_x + wing_size, end_y]], np.int32)
                cv2.fillPoly(img, [pts], arrow_color)

            is_rev = (object_type == "reverse_arrow")
            if double_arrow:
                draw_single_arrow_logic(cx - 5, is_reverse=is_rev)
                draw_single_arrow_logic(cx + 5, is_reverse=is_rev)
            else:
                draw_single_arrow_logic(cx, is_reverse=is_rev)

        elif object_type == "rightarrow":
            base_x, tip_x = cx - 30, cx - 10
            cv2.line(img, (base_x, tip_y), (tip_x, tip_y), color, thickness)
            pts = np.array([[tip_x, tip_y], [tip_x - head_size, tip_y - wing_size], [tip_x - head_size, tip_y + wing_size]], np.int32)
            cv2.fillPoly(img, [pts], color)

        elif object_type == "leftarrow":
            base_x, tip_x = cx + 30, cx + 10
            cv2.line(img, (base_x, tip_y), (tip_x, tip_y), color, thickness)
            pts = np.array([[tip_x, tip_y], [tip_x + head_size, tip_y - wing_size], [tip_x + head_size, tip_y + wing_size]], np.int32)
            cv2.fillPoly(img, [pts], color)

        elif object_type == "lline":
            # Thin 1px horizontal line
            stop_x = end_x if end_x is not None else img.shape[1]
            cv2.line(img, (cx, tip_y), (int(stop_x), tip_y), color, 1)

        elif object_type == "box_transparent":
            if box_w is not None and box_h is not None:
                # Calculate coordinates based on passed width/height
                x1, y1 = cx - (box_w // 2), tip_y - (box_h // 2)
                x2, y2 = x1 + box_w, y1 + box_h
                
                # Overlay for transparency
                overlay = img.copy()
                cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)
                cv2.addWeighted(overlay, box_alpha, img, 1 - box_alpha, 0, img)
                
                # 1px Border
                cv2.rectangle(img, (x1, y1), (x2, y2), color, 1)

        else:
            shape_y = tip_y - 12 if place_at_high else tip_y + 12
            if object_type == "circle":
                cv2.circle(img, (cx, shape_y), 6, color, thickness=thickness)
            elif object_type == "dot":
                cv2.circle(img, (cx, shape_y), 6, color, thickness=-1)
            elif object_type == "pentagon":
                radius = 8
                pts = np.array([[cx, shape_y - radius], [cx + int(radius * 0.95), shape_y - int(radius * 0.31)], [cx + int(radius * 0.58), shape_y + int(radius * 0.81)], [cx - int(radius * 0.58), shape_y + int(radius * 0.81)], [cx - int(radius * 0.95), shape_y - int(radius * 0.31)]], np.int32)
                cv2.fillPoly(img, [pts], color)
            elif object_type == "star":
                outer_rad, inner_rad = 11, 5
                pts = []
                for i in range(10):
                    angle = i * (np.pi / 5) - (np.pi / 2)
                    r = outer_rad if i % 2 == 0 else inner_rad
                    pts.append([cx + int(np.cos(angle) * r), shape_y + int(np.sin(angle) * r)])
                cv2.fillPoly(img, [np.array(pts, np.int32)], color)

    # 3. Text Placement Logic
    if not (custom_text or fvg_swing_type is not None):
        return

    if is_marked:
        is_vertical_obj = object_type in ["arrow", "reverse_arrow"]
        if is_vertical_obj:
            reach = (shaft_length + head_size + 4)
        elif object_type == "box_transparent" and box_h is not None:
            reach = (box_h // 2) + 4
        else:
            reach = 14
    else:
        reach = 4

    if place_at_high:
        base_text_y = tip_y - reach
    else:
        base_text_y = tip_y + reach + 10

    if custom_text:
        (tw, th), _ = cv2.getTextSize(custom_text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, text_thickness)
        cv2.putText(img, custom_text, (cx - tw // 2, int(base_text_y)),
                    cv2.FONT_HERSHEY_SIMPLEX, font_scale, arrow_color, text_thickness)
        fvg_swing_type_y = (base_text_y - 15) if place_at_high else (base_text_y + 15)
    else:
        fvg_swing_type_y = base_text_y

    if fvg_swing_type is not None:
        cv2.putText(img, str(fvg_swing_type), (cx - 8, int(fvg_swing_type_y)), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 0), 2)
        cv2.putText(img, str(fvg_swing_type), (cx - 8, int(fvg_swing_type_y)), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1)                   

def label_objects(
    img,
    cx,
    y_rect,
    h_rect,
    fvg_swing_type=None,                  
    custom_text=None,           
    object_type="arrow",       
    is_bullish_arrow=True,     
    is_marked=False,
    double_arrow=False,
    arrow_color=(0, 255, 0),
    object_color=(0, 255, 0),
    font_scale=0.55,
    text_thickness=2,
    label_position="auto",
    end_x=None,
    box_w=None,           # External function provides this
    box_h=None,           # External function provides this
    box_alpha=0.3,        # Transparency threshold
    start_x=None,         # NEW: For horizontal line start point
    stop_x=None,          # NEW: For horizontal line end point
    box_color=(0, 0, 0),  # NEW: Box color parameter
    no_border=True        # NEW: Box border control
):
    color = object_color if object_color != (0, 255, 0) else arrow_color

    # Dimensions for markers
    shaft_length = 26
    head_size = 9
    thickness = 2
    wing_size = 7 if double_arrow else 6

    # 1. Determine Vertical Placement (Anchor Point)
    if label_position == "auto":
        place_at_high = not is_bullish_arrow  # HH/LH → top, ll/LL → bottom
    else:
        place_at_high = (label_position.lower() == "high")

    # tip_y is the exact pixel of the wick tip (top or bottom)
    tip_y = y_rect if place_at_high else (y_rect + h_rect)

    # 2. Draw Objects (Arrows/Shapes/Lines) ONLY if is_marked is True
    if is_marked:
        if object_type in ["arrow", "reverse_arrow"]:
            def draw_single_arrow_logic(center_x: int, is_reverse=False):
                if not is_reverse:
                    if place_at_high: # Tip at top, shaft goes UP
                        shaft_start_y = tip_y - head_size
                        cv2.line(img, (center_x, shaft_start_y), (center_x, shaft_start_y - shaft_length), arrow_color, thickness)
                        pts = np.array([[center_x, tip_y - 2], [center_x - wing_size, tip_y - head_size], [center_x + wing_size, tip_y - head_size]], np.int32)
                    else: # Tip at bottom, shaft goes DOWN
                        shaft_start_y = tip_y + head_size
                        cv2.line(img, (center_x, shaft_start_y), (center_x, shaft_start_y + shaft_length), arrow_color, thickness)
                        pts = np.array([[center_x, tip_y + 2], [center_x - wing_size, tip_y + head_size], [center_x + wing_size, tip_y + head_size]], np.int32)
                else:
                    base_y = tip_y - 5 if place_at_high else tip_y + 5
                    end_y = base_y - shaft_length if place_at_high else base_y + shaft_length
                    cv2.line(img, (center_x, base_y), (center_x, end_y), arrow_color, thickness)
                    tip_offset = -head_size if place_at_high else head_size
                    pts = np.array([[center_x, end_y + tip_offset], [center_x - wing_size, end_y], [center_x + wing_size, end_y]], np.int32)
                cv2.fillPoly(img, [pts], arrow_color)

            is_rev = (object_type == "reverse_arrow")
            if double_arrow:
                draw_single_arrow_logic(cx - 5, is_reverse=is_rev)
                draw_single_arrow_logic(cx + 5, is_reverse=is_rev)
            else:
                draw_single_arrow_logic(cx, is_reverse=is_rev)

        elif object_type == "rightarrow":
            base_x, tip_x = cx - 30, cx - 10
            cv2.line(img, (base_x, tip_y), (tip_x, tip_y), color, thickness)
            pts = np.array([[tip_x, tip_y], [tip_x - head_size, tip_y - wing_size], [tip_x - head_size, tip_y + wing_size]], np.int32)
            cv2.fillPoly(img, [pts], color)

        elif object_type == "leftarrow":
            base_x, tip_x = cx + 30, cx + 10
            cv2.line(img, (base_x, tip_y), (tip_x, tip_y), color, thickness)
            pts = np.array([[tip_x, tip_y], [tip_x + head_size, tip_y - wing_size], [tip_x + head_size, tip_y + wing_size]], np.int32)
            cv2.fillPoly(img, [pts], color)

        elif object_type == "lline":
            # Thin 1px horizontal line with start and stop points
            start_x_final = start_x if start_x is not None else cx
            stop_x_final = stop_x if stop_x is not None else (end_x if end_x is not None else img.shape[1])
            cv2.line(img, (int(start_x_final), tip_y), (int(stop_x_final), tip_y), color, 1)

        elif object_type == "box_transparent":
            if box_w is not None and box_h is not None:
                # Calculate coordinates based on passed width/height
                x1, y1 = cx - (box_w // 2), tip_y - (box_h // 2)
                x2, y2 = x1 + box_w, y1 + box_h
                
                # Overlay for transparency
                overlay = img.copy()
                cv2.rectangle(overlay, (x1, y1), (x2, y2), box_color, -1)
                cv2.addWeighted(overlay, box_alpha, img, 1 - box_alpha, 0, img)
                
                # Border only if not specified as no border
                if not no_border:
                    cv2.rectangle(img, (x1, y1), (x2, y2), color, 1)

        else:
            shape_y = tip_y - 12 if place_at_high else tip_y + 12
            if object_type == "circle":
                cv2.circle(img, (cx, shape_y), 6, color, thickness=thickness)
            elif object_type == "dot":
                cv2.circle(img, (cx, shape_y), 6, color, thickness=-1)
            elif object_type == "pentagon":
                radius = 8
                pts = np.array([[cx, shape_y - radius], [cx + int(radius * 0.95), shape_y - int(radius * 0.31)], [cx + int(radius * 0.58), shape_y + int(radius * 0.81)], [cx - int(radius * 0.58), shape_y + int(radius * 0.81)], [cx - int(radius * 0.95), shape_y - int(radius * 0.31)]], np.int32)
                cv2.fillPoly(img, [pts], color)
            elif object_type == "star":
                outer_rad, inner_rad = 11, 5
                pts = []
                for i in range(10):
                    angle = i * (np.pi / 5) - (np.pi / 2)
                    r = outer_rad if i % 2 == 0 else inner_rad
                    pts.append([cx + int(np.cos(angle) * r), shape_y + int(np.sin(angle) * r)])
                cv2.fillPoly(img, [np.array(pts, np.int32)], color)

    # 3. Text Placement Logic
    if not (custom_text or fvg_swing_type is not None):
        return

    if is_marked:
        is_vertical_obj = object_type in ["arrow", "reverse_arrow"]
        if is_vertical_obj:
            reach = (shaft_length + head_size + 4)
        elif object_type == "box_transparent" and box_h is not None:
            reach = (box_h // 2) + 4
        else:
            reach = 14
    else:
        reach = 4

    if place_at_high:
        base_text_y = tip_y - reach
    else:
        base_text_y = tip_y + reach + 10

    if custom_text:
        (tw, th), _ = cv2.getTextSize(custom_text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, text_thickness)
        cv2.putText(img, custom_text, (cx - tw // 2, int(base_text_y)),
                    cv2.FONT_HERSHEY_SIMPLEX, font_scale, arrow_color, text_thickness)
        fvg_swing_type_y = (base_text_y - 15) if place_at_high else (base_text_y + 15)
    else:
        fvg_swing_type_y = base_text_y

    if fvg_swing_type is not None:
        cv2.putText(img, str(fvg_swing_type), (cx - 8, int(fvg_swing_type_y)), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 0), 2)
        cv2.putText(img, str(fvg_swing_type), (cx - 8, int(fvg_swing_type_y)), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1)

def swing_points(user_id, max_symbols_parallel=5):
    lagos_tz = pytz.timezone('Africa/Lagos')
    
    dev_dict = load_developers_dictionary()
    cfg = dev_dict.get(str(user_id))
    if not cfg:
        return f"[User {user_id}] Error: User not in dictionary."
    
    # Use global DEV_PATH with user_id
    user_root = os.path.join(DEV_PATH, str(user_id))
    ohlc_source_root = os.path.join(user_root, "ohlc")
    
    # Get account management from user config
    account_management = cfg.get("accountmanagement", {})
    if not account_management:
        return f"[User {user_id}] Error: accountmanagement not found in config."
    
    define_candles = account_management.get("chart", {}).get("define_candles", {})
    keyword = "swing_points"
    matching_configs = [(k, v) for k, v in define_candles.items() if keyword in k.lower()]
    if not matching_configs:
        return f"[User {user_id}] Error: No configuration found for '{keyword}'."
    
    # Get symbols from user's symbols_dictionary
    symbols_dict = account_management.get("symbols_dictionary", {})
    user_symbols = []
    for category, symbol_list in symbols_dict.items():
        if isinstance(symbol_list, list):
            for sym in symbol_list:
                if sym and sym not in user_symbols:
                    user_symbols.append(sym)
    
    if not user_symbols:
        return f"[User {user_id}] Error: No symbols found in symbols_dictionary."
    
    total_marked_all, processed_charts_all = 0, 0

    def resolve_marker(raw):
        if not raw: return None, False
        raw = str(raw).lower().strip()
        if raw in ["arrow", "arrows", "singlearrow"]: return "arrow", False
        if raw in ["doublearrow", "doublearrows"]: return "arrow", True
        if raw in ["reverse_arrow", "reversearrow"]: return "reverse_arrow", False
        if raw in ["reverse_doublearrow", "reverse_doublearrows"]: return "reverse_arrow", True
        if raw in ["rightarrow", "right_arrow"]: return "rightarrow", False
        if raw in ["leftarrow", "left_arrow"]: return "leftarrow", False
        if "dot" in raw: return "dot", False
        return raw, False

    # Aesthetic print header
    print("\n" + "="*80)
    print(f"🚀 SWING POINTS ANALYSIS - User {user_id}".center(80))
    print("="*80)

    # Process each config
    for config_key, hlll_cfg in matching_configs:
        bars = hlll_cfg.get("BARS", 101)
        output_filename_base = hlll_cfg.get("filename", "highers.json")
        direction = hlll_cfg.get("read_candles_from", "new_old")
        
        neighbor_left = hlll_cfg.get("NEIGHBOR_LEFT", 5)
        neighbor_right = hlll_cfg.get("NEIGHBOR_RIGHT", 5)
        label_cfg = hlll_cfg.get("label", {})
        hh_text = label_cfg.get("swinghighs_text", "HH")
        ll_text = label_cfg.get("swinglows_text", "ll")
        cm_text = label_cfg.get("contourmaker_text", "")
        label_at = label_cfg.get("label_at", {})
        hh_pos = label_at.get("swing_highs", "high").lower()
        ll_pos = label_at.get("swing_lows", "low").lower()
        
        color_map = {"green": (0, 255, 0), "red": (255, 0, 0), "blue": (0, 0, 255)}
        hh_col = color_map.get(label_at.get("swing_highs_color", "red").lower(), (255, 0, 0))
        ll_col = color_map.get(label_at.get("swing_lows_color", "green").lower(), (0, 255, 0))
        
        hh_obj, hh_dbl = resolve_marker(label_at.get("swing_highs_marker", "arrow"))
        ll_obj, ll_dbl = resolve_marker(label_at.get("swing_lows_marker", "arrow"))
        hh_cm_obj, hh_cm_dbl = resolve_marker(label_at.get("swing_highs_contourmaker_marker", ""))
        ll_cm_obj, ll_cm_dbl = resolve_marker(label_at.get("swing_lows_contourmaker_marker", ""))

        # Prepare arguments for parallel processing using user symbols only
        symbol_args = []
        for sym in user_symbols:
            # Check if symbol folder exists in ohlc source
            sym_folder = os.path.join(ohlc_source_root, sym.replace(" ", "_"))
            if os.path.isdir(sym_folder):
                symbol_args.append((
                    sym, ohlc_source_root, user_id, config_key, hlll_cfg,
                    neighbor_left, neighbor_right, hh_text, ll_text, cm_text,
                    hh_pos, ll_pos, hh_col, ll_col, hh_obj, ll_obj, hh_dbl, ll_dbl,
                    hh_cm_obj, ll_cm_obj, hh_cm_dbl, ll_cm_dbl,
                    bars, direction, output_filename_base
                ))
        
        if not symbol_args:
            continue
        
        # Use ThreadPool to avoid nested daemon processes
        with ThreadPool(processes=max_symbols_parallel) as symbol_pool:
            symbol_results = symbol_pool.map(process_single_symbol, symbol_args)
            
            # Aggregate results
            for symbol_swings_high, symbol_swings_low, symbol_timeframes, symbol_name in symbol_results:
                total_marked_all += (symbol_swings_high + symbol_swings_low)
                processed_charts_all += len(symbol_timeframes)
                
                # Print symbol summary
                if symbol_timeframes:
                    total_symbol_swings = symbol_swings_high + symbol_swings_low
                    if total_symbol_swings > 0:
                        print(f"\n {symbol_name} SWING POINTS:")
                        print(f"   ├─ Timeframes processed: {len(symbol_timeframes)}")
                        print(f"   ├─ 🔴 SWING HIGHS: {symbol_swings_high}")
                        print(f"   ├─ 🟢 SWING LOWS: {symbol_swings_low}")
                        print(f"   └─ 📊 TOTAL SWINGS: {total_symbol_swings}")
                        print(f"   {'.' * 50}")

    # Final summary with beautiful formatting
    print("\n" + "="*80)
    print("🎯 SWING POINTS COMPLETED".center(80))
    print(f"📊 Total Swings: {total_marked_all} | Charts Processed: {processed_charts_all}".center(80))
    print("="*80)
    
    return f"[User {user_id}] Swing points analysis completed. Total swings: {total_marked_all}"

def process_single_symbol(args):
    """Process a single symbol across all its timeframes"""
    (sym, base_folder, user_id, config_key, hlll_cfg,
     neighbor_left, neighbor_right, hh_text, ll_text, cm_text,
     hh_pos, ll_pos, hh_col, ll_col, hh_obj, ll_obj, hh_dbl, ll_dbl,
     hh_cm_obj, ll_cm_obj, hh_cm_dbl, ll_cm_dbl,
     bars, direction, output_filename_base) = args
    
    symbol_swings_high = 0
    symbol_swings_low = 0
    symbol_timeframes = []
    
    # base_folder is already the OHLC source root: DEV_PATH/{user_id}/ohlc
    # Check if symbol exists in ohlc source
    sym_folder_name = sym.replace(" ", "_")
    sym_p = os.path.join(base_folder, sym_folder_name)
    if not os.path.isdir(sym_p):
        return (0, 0, [], sym)
    
    # Get user's timeframes from config (or scan folders)
    timeframes = []
    for tf in sorted(os.listdir(sym_p)):
        tf_p = os.path.join(sym_p, tf)
        if os.path.isdir(tf_p):
            timeframes.append(tf)
    
    if not timeframes:
        return (0, 0, [], sym)
    
    for tf in timeframes:
        # Get paths using the new function signature
        paths = get_analysis_paths(user_id, sym, tf, direction, bars, output_filename_base)
        config_path = os.path.join(paths["output_dir"], "config.json")
        
        # Check if source files exist - skip silently if not
        if not os.path.exists(paths["source_json"]) or not os.path.exists(paths["source_chart"]):
            continue
        
        try:
            with open(paths["source_json"], 'r', encoding='utf-8') as f:
                data = sorted(json.load(f), key=lambda x: x.get('candle_number', 0))
            
            # ADD CENTER_PRICE TO EACH CANDLE
            for candle in data:
                if 'high' in candle and 'low' in candle:
                    candle['center_price'] = (candle['high'] + candle['low']) / 2
                else:
                    candle['center_price'] = None
            
            img = cv2.imread(paths["source_chart"])
            if img is None: 
                continue
            
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, (35, 50, 50), (85, 255, 255)) | cv2.inRange(hsv, (0, 50, 50), (10, 255, 255))
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            if len(contours) == 0: 
                continue

            contours = sorted(contours, key=lambda c: cv2.boundingRect(c)[0])
            
            if len(data) != len(contours):
                min_len = min(len(data), len(contours))
                data = data[:min_len]
                contours = contours[:min_len]

            for idx, contour in enumerate(contours):
                x, y, w, h = cv2.boundingRect(contour)
                data[idx].update({
                    "candle_center_x": x + (w // 2),
                    "candle_center_y": y + (h // 2),
                    "candle_x": x + (w // 2),
                    "candle_y": y,
                    "candle_width": w,
                    "candle_height": h,
                    "candle_left": x,
                    "candle_right": x + w,
                    "candle_top": y,
                    "candle_bottom": y + h
                })

            n = len(data)
            swing_count_in_chart = 0
            swing_highs_in_chart = 0
            swing_lows_in_chart = 0
            
            # Handle neighbor boundaries based on zero values
            if neighbor_left == 0 and neighbor_right == 0:
                # Special case: mark every red candle as swing low and every green candle as swing high
                for i in range(n):
                    candle_close = data[i].get('close', 0)
                    candle_open = data[i].get('open', 0)
                    is_bull = candle_close >= candle_open
                    
                    if is_bull:
                        swing_highs_in_chart += 1
                        symbol_swings_high += 1
                        active_color = hh_col
                        custom_text = hh_text
                        obj_type = hh_obj
                        dbl_arrow = hh_dbl
                        position = hh_pos
                    else:
                        swing_lows_in_chart += 1
                        symbol_swings_low += 1
                        active_color = ll_col
                        custom_text = ll_text
                        obj_type = ll_obj
                        dbl_arrow = ll_dbl
                        position = ll_pos
                    
                    swing_count_in_chart += 1
                    
                    label_objects_and_text(
                        img, data[i]["candle_center_x"], data[i]["candle_center_y"], data[i]["candle_height"],
                        fvg_swing_type=data[i]['candle_number'],
                        custom_text=custom_text,
                        object_type=obj_type,
                        is_bullish_arrow=is_bull,
                        is_marked=True,
                        double_arrow=dbl_arrow,
                        arrow_color=active_color,
                        label_position=position
                    )
                    
                    m_idx = i + 1
                    contour_maker_entry = None
                    if m_idx < n:
                        cm_obj = ll_cm_obj if not is_bull else hh_cm_obj
                        cm_dbl = ll_cm_dbl if not is_bull else hh_cm_dbl
                        
                        if cm_obj:
                            label_objects_and_text(
                                img, data[m_idx]["candle_center_x"], data[m_idx]["candle_center_y"], data[m_idx]["candle_height"],
                                custom_text=cm_text,
                                object_type=cm_obj,
                                is_bullish_arrow=is_bull,
                                is_marked=True,
                                double_arrow=cm_dbl,
                                arrow_color=active_color,
                                label_position=position
                            )
                        
                        data[m_idx]["is_contour_maker"] = True
                        contour_maker_entry = data[m_idx].copy()
                        contour_maker_entry.update({
                            "draw_x": data[m_idx]["candle_center_x"],
                            "draw_y": data[m_idx]["candle_center_y"],
                            "draw_w": data[m_idx]["candle_width"],
                            "draw_h": data[m_idx]["candle_height"],
                            "draw_left": data[m_idx]["candle_left"],
                            "draw_right": data[m_idx]["candle_right"],
                            "draw_top": data[m_idx]["candle_top"],
                            "draw_bottom": data[m_idx]["candle_bottom"],
                            "is_contour_maker": True
                        })
                    
                    data[i].update({
                        "swing_type": "swing_low" if not is_bull else "swing_high",
                        "is_swing": True,
                        "active_color": active_color,
                        "draw_x": data[i]["candle_center_x"],
                        "draw_y": data[i]["candle_center_y"],
                        "draw_w": data[i]["candle_width"],
                        "draw_h": data[i]["candle_height"],
                        "draw_left": data[i]["candle_left"],
                        "draw_right": data[i]["candle_right"],
                        "draw_top": data[i]["candle_top"],
                        "draw_bottom": data[i]["candle_bottom"],
                        "contour_maker": contour_maker_entry,
                        "m_idx": m_idx if m_idx < n else None
                    })
            
            else:
                # Original logic for when neighbors are not both zero
                if neighbor_left == 0 and neighbor_right == 0:
                    start_idx = 0
                    end_idx = n
                elif neighbor_left == 0:
                    start_idx = 0
                    end_idx = n - neighbor_right
                elif neighbor_right == 0:
                    start_idx = neighbor_left
                    end_idx = n
                else:
                    start_idx = neighbor_left
                    end_idx = n - neighbor_right

                for i in range(start_idx, end_idx):
                    curr_h, curr_l = data[i]['high'], data[i]['low']
                    
                    if neighbor_left > 0:
                        l_h = [d['high'] for d in data[i - neighbor_left:i]]
                        l_l = [d['low'] for d in data[i - neighbor_left:i]]
                    else:
                        l_h = []
                        l_l = []
                    
                    if neighbor_right > 0:
                        r_h = [d['high'] for d in data[i + 1:i + 1 + neighbor_right]]
                        r_l = [d['low'] for d in data[i + 1:i + 1 + neighbor_right]]
                    else:
                        r_h = []
                        r_l = []
                    
                    is_hh = True
                    if len(l_h) > 0 and curr_h <= max(l_h):
                        is_hh = False
                    if len(r_h) > 0 and curr_h <= max(r_h):
                        is_hh = False
                    
                    is_ll = True
                    if len(l_l) > 0 and curr_l >= min(l_l):
                        is_ll = False
                    if len(r_l) > 0 and curr_l >= min(r_l):
                        is_ll = False
                    
                    if neighbor_left == 0 and neighbor_right == 0:
                        if i + 1 < n:
                            if curr_h > data[i+1]['high']:
                                is_hh = True
                                is_ll = False
                            elif curr_l < data[i+1]['low']:
                                is_hh = False
                                is_ll = True
                            else:
                                continue
                        else:
                            if i - 1 >= 0:
                                if curr_h > data[i-1]['high']:
                                    is_hh = True
                                    is_ll = False
                                elif curr_l < data[i-1]['low']:
                                    is_hh = False
                                    is_ll = True
                                else:
                                    continue
                            else:
                                is_hh = False
                                is_ll = True
                    
                    if not (is_hh or is_ll):
                        continue
                    
                    swing_count_in_chart += 1
                    is_bull = is_ll
                    
                    if is_bull:
                        swing_lows_in_chart += 1
                        symbol_swings_low += 1
                    else:
                        swing_highs_in_chart += 1
                        symbol_swings_high += 1
                        
                    active_color = ll_col if is_bull else hh_col
                    custom_text = ll_text if is_bull else hh_text
                    obj_type = ll_obj if is_bull else hh_obj
                    dbl_arrow = ll_dbl if is_bull else hh_dbl
                    position = ll_pos if is_bull else hh_pos

                    label_objects_and_text(
                        img, data[i]["candle_center_x"], data[i]["candle_center_y"], data[i]["candle_height"],
                        fvg_swing_type=data[i]['candle_number'],
                        custom_text=custom_text,
                        object_type=obj_type,
                        is_bullish_arrow=is_bull,
                        is_marked=True,
                        double_arrow=dbl_arrow,
                        arrow_color=active_color,
                        label_position=position
                    )

                    m_idx = i + neighbor_right if neighbor_right > 0 else i + 1
                    contour_maker_entry = None
                    if m_idx < n:
                        cm_obj = ll_cm_obj if is_bull else hh_cm_obj
                        cm_dbl = ll_cm_dbl if is_bull else hh_cm_dbl
                        
                        if cm_obj:
                            label_objects_and_text(
                                img, data[m_idx]["candle_center_x"], data[m_idx]["candle_center_y"], data[m_idx]["candle_height"],
                                custom_text=cm_text,
                                object_type=cm_obj,
                                is_bullish_arrow=is_bull,
                                is_marked=True,
                                double_arrow=cm_dbl,
                                arrow_color=active_color,
                                label_position=position
                            )

                        data[m_idx]["is_contour_maker"] = True
                        contour_maker_entry = data[m_idx].copy()
                        contour_maker_entry.update({
                            "draw_x": data[m_idx]["candle_center_x"],
                            "draw_y": data[m_idx]["candle_center_y"],
                            "draw_w": data[m_idx]["candle_width"],
                            "draw_h": data[m_idx]["candle_height"],
                            "draw_left": data[m_idx]["candle_left"],
                            "draw_right": data[m_idx]["candle_right"],
                            "draw_top": data[m_idx]["candle_top"],
                            "draw_bottom": data[m_idx]["candle_bottom"],
                            "is_contour_maker": True
                        })

                    data[i].update({
                        "swing_type": "swing_low" if is_bull else "swing_high",
                        "is_swing": True,
                        "active_color": active_color,
                        "draw_x": data[i]["candle_center_x"],
                        "draw_y": data[i]["candle_center_y"],
                        "draw_w": data[i]["candle_width"],
                        "draw_h": data[i]["candle_height"],
                        "draw_left": data[i]["candle_left"],
                        "draw_right": data[i]["candle_right"],
                        "draw_top": data[i]["candle_top"],
                        "draw_bottom": data[i]["candle_bottom"],
                        "contour_maker": contour_maker_entry,
                        "m_idx": m_idx if m_idx < n else None
                    })

            # Finalize outputs for this specific TF
            os.makedirs(paths["output_dir"], exist_ok=True)
            cv2.imwrite(paths["output_chart"], img)

            config_json = {}
            if os.path.exists(config_path):
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config_json = json.load(f)
                except:
                    config_json = {}
            
            config_json[config_key] = data
            config_json[f"{config_key}_candle_list"] = data 

            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config_json, f, indent=4)
            
            symbol_timeframes.append(tf)
            
        except Exception as e:
            # Silently skip errors
            pass
    
    return (symbol_swings_high, symbol_swings_low, symbol_timeframes, sym)

def fair_value_gaps(user_id):
    lagos_tz = pytz.timezone('Africa/Lagos')
    
    def log(msg, level="INFO"):
        ts = datetime.now(lagos_tz).strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{ts}] [{level}] {msg}")
    
    dev_dict = load_developers_dictionary()
    cfg = dev_dict.get(str(user_id))  # ← FIXED: use user_id
    if not cfg:
        return f"[User {user_id}] Error: User not in dictionary."  # ← FIXED
    
    # user_id is already the parameter, no need to reassign
    user_root = os.path.join(DEV_PATH, str(user_id))
    ohlc_source_root = os.path.join(user_root, "ohlc")
    am_data = get_account_management(user_id)
    if not am_data:
        return f"[User {user_id}] Error: accountmanagement not found in config."  # ← FIXED
    
    # === DYNAMIC SEARCH BY KEYWORD "fvg" IN SECTION NAME ===
    define_candles = am_data.get("chart", {}).get("define_candles", {})
    if not define_candles:
        return f"[{user_id}] Error: 'define_candles' section missing in accountmanagement.json."

    keyword = "fvg"
    matching_configs = []

    for key, section in define_candles.items():
        if isinstance(section, dict) and keyword in key.lower():
            matching_configs.append((key, section))

    if not matching_configs:
        return f"[{user_id}] Error: No section key containing '{keyword}' found in 'define_candles'."

    log(f"Found {len(matching_configs)} FVG configuration(s) matching keyword '{keyword}': {[k for k, _ in matching_configs]}")

    total_marked_all = 0
    processed_charts_all = 0

    for config_key, fvg_cfg in matching_configs:
        log(f"Processing FVG configuration: '{config_key}'")

        # Config extraction
        bars = fvg_cfg.get("BARS", 101)
        output_filename_base = fvg_cfg.get("filename", "fvg.json")
        direction = fvg_cfg.get("read_candles_from", "new_old")
        number_mode = fvg_cfg.get("number_candles", "all").lower()
        validate_filter = fvg_cfg.get("validate_my_condition", False)
        
        # Condition extraction
        conditions = fvg_cfg.get("condition", {})
        do_c1_check = (conditions.get("strong_c1") == "greater")
        do_strength_check = conditions.get("strong_fvg") in ["taller_body", "tallest_body"]
        do_c3_check = (conditions.get("strong_c3") == "greater")
        
        check_c1_type = (conditions.get("c1_candle_type") == "same_with_fvg")
        check_c3_type = (conditions.get("c3_candle_type") == "same_with_fvg")
        c3_closing_cfg = conditions.get("c3_closing")
        fvg_body_size_cfg = str(conditions.get("fvg_body_size", "")).strip().lower()
        
        # Body > Wick requirement toggle
        body_vs_wick_mode = str(conditions.get("c1_c3_higher_body_than_wicks", "")).strip().lower()
        apply_body_vs_wick_rule = (body_vs_wick_mode == "apply")
        
        # Lookback Logic
        raw_lookback = conditions.get("c1_lookback")
        if raw_lookback is None or str(raw_lookback).strip().lower() in ["", "0", "null", "none"]:
            c1_lookback = 0
        else:
            try:
                c1_lookback = min(int(raw_lookback), 5)
            except (ValueError, TypeError):
                c1_lookback = 0
        
        # Label & Color Logic
        label_cfg = fvg_cfg.get("label", {})
        bull_text = label_cfg.get("bullish_text", "+fvg")
        bear_text = label_cfg.get("bearish_text", "-fvg")
        label_at = label_cfg.get("label_at", {})
        
        color_map = {"green": (0, 255, 0), "red": (255, 0, 0)}  # BGR
        bullish_color = color_map.get(label_at.get("bullish_color", "green").lower(), (0, 255, 0))
        bearish_color = color_map.get(label_at.get("bearish_color", "red").lower(), (255, 0, 0))
        
        def resolve_marker(raw):
            raw = str(raw).lower().strip()
            if raw in ["arrow", "arrows", "singlearrow"]: return "arrow", False
            if raw in ["doublearrow", "doublearrows"]: return "arrow", True
            if raw in ["reverse_arrow", "reversearrow"]: return "reverse_arrow", False
            if raw in ["reverse_doublearrow", "reverse_doublearrows"]: return "reverse_arrow", True
            return raw, False
        
        bull_obj, bull_double = resolve_marker(label_at.get("bullish_marker", "arrow"))
        bear_obj, bear_double = resolve_marker(label_at.get("bearish_marker", "arrow"))
        
        number_all = (number_mode == "all")
        number_only_marked = number_mode in ["define_candles", "define_candle", "definecandle"]
        
        total_marked = 0
        processed_charts = 0

        log(f"Starting FVG Analysis with config '{config_key}' | Mode: Left-to-Right Only")

        for sym in sorted(os.listdir(ohlc_source_root)):
            sym_p = os.path.join(ohlc_source_root, sym)
            if not os.path.isdir(sym_p): continue
            
            for tf in sorted(os.listdir(sym_p)):
                tf_path = os.path.join(sym_p, tf)
                if not os.path.isdir(tf_path): continue

                paths = get_analysis_paths(user_id, sym, tf, direction, bars, output_filename_base)

                if not os.path.exists(paths["source_json"]) or not os.path.exists(paths["source_chart"]):
                    continue
                    
                try:
                    with open(paths["source_json"], 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    min_required = 3 + c1_lookback
                    if len(data) < min_required: continue
                    
                    data = sorted(data, key=lambda x: x.get('candle_number', 0))
                    
                    img = cv2.imread(paths["source_chart"])
                    if img is None: continue
                    
                    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
                    mask = cv2.inRange(hsv, (35, 50, 50), (85, 255, 255)) | cv2.inRange(hsv, (0, 50, 50), (10, 255, 255))
                    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    contours = sorted(contours, key=lambda c: cv2.boundingRect(c)[0], reverse=False)
                    
                    marked_count = 0
                    # Storage for the FVG attributes to apply to candles 1, 2, and 3
                    potential_fvgs_map = {} 
                    c1_tags = {} # candle_num -> {fvg_c1: True, c1_for_fvg_number: X}
                    c3_tags = {} # candle_num -> {fvg_c3: True, c3_for_fvg_number: X}
                    
                    # --- Identify Potential FVGs ---
                    for i in range(1 + c1_lookback, len(data) - 1):
                        if i >= len(contours): break
                        
                        c_idx_1 = i - 1 - c1_lookback
                        c1, c2, c3 = data[c_idx_1], data[i], data[i+1]
                        
                        c1_u_wick = round(c1['high'] - max(c1['open'], c1['close']), 5)
                        c1_l_wick = round(min(c1['open'], c1['close']) - c1['low'], 5)
                        c1_total_wick = round(c1_u_wick + c1_l_wick, 5)
                        
                        c3_u_wick = round(c3['high'] - max(c3['open'], c3['close']), 5)
                        c3_l_wick = round(min(c3['open'], c3['close']) - c3['low'], 5)
                        c3_total_wick = round(c3_u_wick + c3_l_wick, 5)
                        
                        body1 = round(abs(c1['close'] - c1['open']), 5)
                        body2 = round(abs(c2['close'] - c2['open']), 5)
                        body3 = round(abs(c3['close'] - c3['open']), 5)
                        
                        height1 = round(c1['high'] - c1['low'], 5)
                        height2 = round(c2['high'] - c2['low'], 5)
                        height3 = round(c3['high'] - c3['low'], 5)
                        
                        fvg_type = None
                        gap_top, gap_bottom = 0, 0
                        
                        if c1['low'] > c3['high']:
                            fvg_type = "bearish"
                            gap_top, gap_bottom = c1['low'], c3['high']
                        elif c1['high'] < c3['low']:
                            fvg_type = "bullish"
                            gap_top, gap_bottom = c3['low'], c1['high']
                        
                        if fvg_type:
                            gap_size = round(abs(gap_top - gap_bottom), 5)
                            is_bullish_fvg_c = c2['close'] > c2['open']
                            
                            c1_type_match = ((fvg_type == "bullish" and c1['close'] > c1['open']) or 
                                            (fvg_type == "bearish" and c1['close'] < c1['open'])) if check_c1_type else True
                            c3_type_match = ((fvg_type == "bullish" and c3['close'] > c3['open']) or 
                                            (fvg_type == "bearish" and c3['close'] < c3['open'])) if check_c3_type else True
                            
                            c3_beyond_wick = (fvg_type == "bearish" and c3['close'] < c2['low']) or \
                                             (fvg_type == "bullish" and c3['close'] > c2['high'])
                            c3_beyond_close = (fvg_type == "bearish" and c3['close'] < c2['close']) or \
                                              (fvg_type == "bullish" and c3['close'] > c2['close'])
                            
                            c3_closing_match = True
                            if c3_closing_cfg == "beyond_wick":    c3_closing_match = c3_beyond_wick
                            elif c3_closing_cfg == "beyond_close": c3_closing_match = c3_beyond_close
                            
                            is_strong_c1 = ((fvg_type == "bearish" and c1['high'] > c2['high']) or 
                                           (fvg_type == "bullish" and c1['low'] < c2['low'])) if do_c1_check else True
                            is_strong_c3 = ((fvg_type == "bearish" and c3['low'] < c2['low']) or 
                                           (fvg_type == "bullish" and c3['high'] > c2['high'])) if do_c3_check else True
                            
                            excess_c1 = round(body2 - body1, 5)
                            excess_c3 = round(body2 - body3, 5)
                            is_strong_fvg = (excess_c1 > 0 and excess_c3 > 0) if do_strength_check else True
                            
                            fvg_durability = True
                            if fvg_body_size_cfg == "sum_c1_c3_body":
                                fvg_durability = (body1 + body3) <= body2
                            elif fvg_body_size_cfg == "sum_c1_c3_height":
                                fvg_durability = (height1 + height3) <= height2
                            elif fvg_body_size_cfg == "multiply_c1_body_by_2":
                                fvg_durability = (body1 * 2) <= body2
                            elif fvg_body_size_cfg == "multiply_c3_body_by_2":
                                fvg_durability = (body3 * 2) <= body2
                            elif fvg_body_size_cfg == "multiply_c1_height_by_2":
                                fvg_durability = (height1 * 2) <= body2
                            elif fvg_body_size_cfg == "multiply_c3_height_by_2":
                                fvg_durability = (height3 * 2) <= body2
                            
                            meets_all = all([
                                c1_type_match, c3_type_match, c3_closing_match,
                                is_strong_c1, is_strong_c3, is_strong_fvg, fvg_durability
                            ])
                            
                            if not validate_filter or (validate_filter and meets_all):
                                # Candle 2 (The FVG) Data
                                enriched_c2 = c2.copy()
                                enriched_c2.update({
                                    "fvg_type": fvg_type,
                                    "fvg_gap_size": gap_size,
                                    "fvg_gap_top": round(gap_top, 5),
                                    "fvg_gap_bottom": round(gap_bottom, 5),
                                    "c1_lookback_used": c1_lookback,
                                    "c1_body_size": body1,
                                    "c2_body_size": body2,
                                    "c3_body_size": body3,
                                    "c1_height": height1,
                                    "c2_height": height2,
                                    "c3_height": height3,
                                    "c1_upper_and_lower_wick": c1_total_wick,
                                    "c1_upper_and_lower_wick_against_body": round(body1 - c1_total_wick, 5),
                                    "c1_upper_and_lower_wick_higher": c1_total_wick > body1,
                                    "c1_body_higher": body1 >= c1_total_wick,
                                    "c3_upper_and_lower_wick": c3_total_wick,
                                    "c3_upper_and_lower_wick_against_body": round(body3 - c3_total_wick, 5),
                                    "c3_upper_and_lower_wick_higher": c3_total_wick > body3,
                                    "c3_body_higher": body3 >= c3_total_wick,
                                    "fvg_body_size_durability": fvg_durability,
                                    "c1_candletype_withfvg": c1_type_match,
                                    "c3_candletype_withfvg": c3_type_match,
                                    "c3_beyond_wick": c3_beyond_wick,
                                    "is_strong_c1": is_strong_c1,
                                    "is_strong_c3": is_strong_c3,
                                    "is_strong_fvg": is_strong_fvg,
                                    "c2_body_excess_against_c1": excess_c1,
                                    "c2_body_excess_against_c3": excess_c3,
                                    "meets_all_conditions": meets_all,
                                    "is_fvg": True,
                                    "_contour_idx": i,
                                    "_is_bull_c2": is_bullish_fvg_c
                                })
                                potential_fvgs_map[c2.get('candle_number')] = enriched_c2
                                
                                # Tag Candle 1 and Candle 3 for later list construction
                                c1_tags[c1.get('candle_number')] = {"fvg_c1": True, "c1_for_fvg_number": c2.get('candle_number')}
                                c3_tags[c3.get('candle_number')] = {"fvg_c3": True, "c3_for_fvg_number": c2.get('candle_number')}

                    # --- Build Final JSON (Flat List Structure) ---
                    fvg_results = []
                    max_gap_found = max([p["fvg_gap_size"] for p in potential_fvgs_map.values()], default=0)
                    
                    for idx, candle in enumerate(data):
                        fvg_swing_type = candle.get('candle_number')
                        
                        # Apply contour/coordinate data to every candle
                        if idx < len(contours):
                            x_c, y_c, w_c, h_c = cv2.boundingRect(contours[idx])
                            candle.update({
                                "candle_x": x_c + w_c // 2, "candle_y": y_c, "candle_width": w_c, "candle_height": h_c,
                                "candle_left": x_c, "candle_right": x_c + w_c, "candle_top": y_c, "candle_bottom": y_c + h_c,
                                "draw_x": x_c + w_c // 2, "draw_y": y_c, "draw_w": w_c, "draw_h": h_c,
                                "draw_left": x_c, "draw_right": x_c + w_c, "draw_top": y_c, "draw_bottom": y_c + h_c
                            })

                        # If this candle is C2 (The FVG)
                        if fvg_swing_type in potential_fvgs_map:
                            entry = potential_fvgs_map[fvg_swing_type]
                            # Sync coordinates from the base candle to the enriched one
                            coord_keys = ["candle_x", "candle_y", "candle_width", "candle_height", "candle_left", "candle_right", "candle_top", "candle_bottom", "draw_x", "draw_y", "draw_w", "draw_h", "draw_left", "draw_right", "draw_top", "draw_bottom"]
                            entry.update({k: candle[k] for k in coord_keys if k in candle})

                            is_tallest = (entry["fvg_gap_size"] == max_gap_found)
                            wick_compromised = (entry["c1_upper_and_lower_wick_higher"] or entry["c3_upper_and_lower_wick_higher"])
                            entry["constestant_fvg_chosed"] = is_tallest and (wick_compromised if apply_body_vs_wick_rule else True)
                            
                            body_condition_ok = ((entry["c1_body_higher"] and entry["c3_body_higher"]) or entry["constestant_fvg_chosed"]) if apply_body_vs_wick_rule else True
                            
                            if body_condition_ok:
                                c_idx = entry["_contour_idx"]
                                x_rect, y_rect, w_rect, h_rect = cv2.boundingRect(contours[c_idx])
                                label_objects_and_text(
                                    img=img, cx=x_rect + w_rect // 2, y_rect=y_rect, h_rect=h_rect,
                                    fvg_swing_type=fvg_swing_type if (number_all or number_only_marked) else None,
                                    custom_text=bull_text if entry["fvg_type"] == "bullish" else bear_text,
                                    object_type=bull_obj if entry["fvg_type"] == "bullish" else bear_obj,
                                    is_bullish_arrow=entry["_is_bull_c2"], is_marked=True,
                                    double_arrow=bull_double if entry["fvg_type"] == "bullish" else bear_double,
                                    arrow_color=bullish_color if entry["_is_bull_c2"] else bearish_color,
                                    label_position="low" if entry["_is_bull_c2"] else "high"
                                )
                                final_entry = {k: v for k, v in entry.items() if not k.startswith("_") and k != "fvg_gap_size"}
                                fvg_results.append(final_entry)
                                marked_count += 1
                                continue 
                        
                        # If this candle is C1 or C3 for an FVG, apply the tags
                        if fvg_swing_type in c1_tags:
                            candle.update(c1_tags[fvg_swing_type])
                        if fvg_swing_type in c3_tags:
                            candle.update(c3_tags[fvg_swing_type])

                        fvg_results.append(candle)
                    
                    if marked_count > 0 or (number_all and len(data) > 0):
                        os.makedirs(paths["output_dir"], exist_ok=True)
                        cv2.imwrite(paths["output_chart"], img)
                        config_path = os.path.join(paths["output_dir"], "config.json")
                        try:
                            config_content = {}
                            if os.path.exists(config_path):
                                with open(config_path, 'r', encoding='utf-8') as f:
                                    try:
                                        config_content = json.load(f)
                                        if not isinstance(config_content, dict): config_content = {}
                                    except: config_content = {}
                            config_content[config_key] = fvg_results
                            with open(config_path, 'w', encoding='utf-8') as f:
                                json.dump(config_content, f, indent=4)
                        except Exception as e:
                            log(f"Config sync failed for {sym}/{tf}: {e}", "WARN")

                        processed_charts += 1
                        total_marked += marked_count
                        
                except Exception as e:
                    log(f"Error processing {sym}/{tf} with config '{config_key}': {e}", "ERROR")

        log(f"Completed config '{config_key}': FVGs marked: {total_marked} | Charts: {processed_charts}")
        total_marked_all += total_marked
        processed_charts_all += processed_charts

    return f"Done (all FVG configs). Total FVGs: {total_marked_all} | Total Charts: {processed_charts_all}"

def fvg_swing_points(user_id):
    lagos_tz = pytz.timezone('Africa/Lagos')
    
    def log(msg, level="INFO"):
        ts = datetime.now(lagos_tz).strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{ts}] [{level}] {msg}")

    dev_dict = load_developers_dictionary()
    cfg = dev_dict.get(str(user_id))  # ← FIXED: use user_id
    if not cfg:
        return f"[User {user_id}] Error: User not in dictionary."  # ← FIXED

    # user_id is already the parameter, no need to reassign
    user_root = os.path.join(DEV_PATH, str(user_id))
    ohlc_source_root = os.path.join(user_root, "ohlc")
    am_data = get_account_management(user_id)
    if not am_data:
        return f"[User {user_id}] Error: accountmanagement not found in config."  # ← FIXED

    # Find FVG configuration section(s)
    define_candles = am_data.get("chart", {}).get("define_candles", {})
    fvg_configs = [(k, v) for k, v in define_candles.items() if "fvg" in k.lower()]
    
    if not fvg_configs:
        return f"[{user_id}] Warning: No FVG config found → cannot determine parameters."

    config_key, fvg_cfg = fvg_configs[0]
    log(f"Using FVG config section: {config_key} for swing detection parameters")

    direction = fvg_cfg.get("read_candles_from", "new_old")
    bars = fvg_cfg.get("BARS", 301)
    output_filename_base = fvg_cfg.get("filename", "fvg.json")

    NEIGHBOR_LEFT = fvg_cfg.get("NEIGHBOR_LEFT", 5)
    NEIGHBOR_RIGHT = fvg_cfg.get("NEIGHBOR_RIGHT", 5)

    HH_TEXT = "fvg-HH"
    ll_TEXT = "fvg-ll"
    CM_TEXT = "m"  
    color_map = {"green": (0, 255, 0), "red": (255, 0, 0)}
    HH_COLOR = color_map["red"]
    ll_COLOR = color_map["green"]

    total_swings_added = 0
    processed_charts = 0

    for sym in sorted(os.listdir(ohlc_source_root)):
        sym_p = os.path.join(ohlc_source_root, sym)
        if not os.path.isdir(sym_p): continue

        for tf in sorted(os.listdir(sym_p)):
            tf_path = os.path.join(sym_p, tf)
            if not os.path.isdir(tf_path): continue

            paths = get_analysis_paths(user_id, sym, tf, direction, bars, output_filename_base)
            config_path = os.path.join(paths["output_dir"], "config.json")
            chart_path = paths["output_chart"]

            if not os.path.exists(config_path) or not os.path.exists(chart_path):
                continue

            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config_content = json.load(f)

                data = config_content.get(config_key)
                if not data or not isinstance(data, list):
                    continue

                data = sorted(data, key=lambda x: x.get('candle_number', 0))
                img = cv2.imread(chart_path)
                if img is None: continue

                n = len(data)
                min_req = NEIGHBOR_LEFT + NEIGHBOR_RIGHT + 1
                if n < min_req: continue

                swing_count = 0
                swings_found = []

                # --- STEP 1: DETECT SWINGS & MARK CONTOUR MAKERS ---
                for i in range(NEIGHBOR_LEFT, n - NEIGHBOR_RIGHT):
                    curr_h, curr_l = data[i]['high'], data[i]['low']
                    left_highs = [d['high'] for d in data[i - NEIGHBOR_LEFT:i]]
                    right_highs = [d['high'] for d in data[i + 1:i + 1 + NEIGHBOR_RIGHT]]
                    left_lows  = [d['low']  for d in data[i - NEIGHBOR_LEFT:i]]
                    right_lows  = [d['low']  for d in data[i + 1:i + 1 + NEIGHBOR_RIGHT]]

                    is_hh = curr_h > max(left_highs) and curr_h > max(right_highs)
                    is_ll = curr_l < min(left_lows)  and curr_l < min(right_lows)

                    if not (is_hh or is_ll): continue

                    swing_count += 1
                    is_bullish_swing = is_ll
                    swing_color = ll_COLOR if is_bullish_swing else HH_COLOR
                    
                    label_objects_and_text(
                        img=img, cx=data[i].get("candle_x"), y_rect=data[i].get("candle_y"), h_rect=data[i].get("candle_height"),
                        fvg_swing_type=data[i].get('candle_number'),
                        custom_text=ll_TEXT if is_bullish_swing else HH_TEXT, object_type="arrow",
                        is_bullish_arrow=is_bullish_swing, is_marked=True,
                        double_arrow=False, arrow_color=swing_color,
                        label_position="low" if is_bullish_swing else "high"
                    )

                    m_idx = i + NEIGHBOR_RIGHT
                    contour_maker_data = None
                    if m_idx < n:
                        label_objects_and_text(
                            img=img, cx=data[m_idx].get("candle_x"), y_rect=data[m_idx].get("candle_y"), h_rect=data[m_idx].get("candle_height"),
                            custom_text=CM_TEXT, object_type="dot",
                            is_bullish_arrow=is_bullish_swing, is_marked=True,
                            double_arrow=False, arrow_color=swing_color,
                            label_position="low" if is_bullish_swing else "high"
                        )
                        
                        data[m_idx].update({"is_contour_maker": True, "contour_maker_for_swing_candle": data[i]['candle_number']})
                        contour_maker_data = {
                            "candle_number": data[m_idx]['candle_number'],
                            "candle_x": data[m_idx].get("candle_x"),
                            "candle_y": data[m_idx].get("candle_y"),
                            "data_index": m_idx
                        }

                    swing_entry = {
                        "candle_number": data[i].get('candle_number'),
                        "swing_type": "higher_low" if is_bullish_swing else "swing_high",
                        "high": curr_h,
                        "low": curr_l
                    }
                    data[i].update({
                        "swing_type": swing_entry["swing_type"],
                        "is_swing": True,
                        "swing_color_bgr": [int(c) for c in swing_color],
                        "m_idx": m_idx if m_idx < n else None,
                        "contour_maker": contour_maker_data
                    })
                    swings_found.append(swing_entry)

                # --- STEP 2: ASSIGN BASE TYPE (SUPPORT/RESISTANCE) ---
                for candle in data:
                    ref_price = candle.get("low")
                    new_flag = None
                    for s in swings_found:
                        if s["swing_type"] == "higher_low" and s["low"] > ref_price:
                            new_flag = "support"
                            break
                        elif s["swing_type"] == "swing_high" and s["high"] < ref_price:
                            new_flag = "resistance"
                            break
                    
                    if new_flag:
                        if candle.get("fvg_c1") is True: candle["fvg_c1_base"] = new_flag
                        if candle.get("is_fvg") is True: candle["fvg_base"] = new_flag
                        if candle.get("fvg_c3") is True: candle["fvg_c3_base"] = new_flag

                # --- STEP 3: DEDUPLICATE ---
                unique_data_dict = {}
                for entry in data:
                    c_num = entry.get("candle_number")
                    if c_num not in unique_data_dict: unique_data_dict[c_num] = entry
                    else:
                        for key, val in entry.items():
                            if key not in unique_data_dict[c_num] or unique_data_dict[c_num][key] is None:
                                unique_data_dict[c_num][key] = val
                data = sorted(unique_data_dict.values(), key=lambda x: x.get('candle_number', 0))

                # --- STEP 4: ASSOCIATE SWINGS AND FIND LIQUIDITY ---
                for i in range(2, len(data)):
                    if data[i].get("fvg_c3") is True:
                        c1, c2, c3 = data[i-2], data[i-1], data[i]
                        family_str = f"{c1['candle_number']}, {c2['candle_number']}, {c3['candle_number']}"
                        
                        target_swing_idx = -1
                        cm_idx = -1
                        for j in range(i + 1, len(data)):
                            if data[j].get("is_swing"):
                                data[j]["swing_type_for_fvgf_number"] = family_str
                                target_swing_idx = j
                                cm_idx = data[j].get("m_idx", -1)
                                break
                        
                        if target_swing_idx != -1 and cm_idx != -1:
                            target_candles = [("c1", c1), ("c2", c2), ("c3", c3)]
                            
                            for label, triad_candle in target_candles:
                                triad_h = triad_candle['high']
                                triad_l = triad_candle['low']
                                found_h_liq = False
                                found_l_liq = False
                                
                                for k in range(cm_idx + 1, len(data)):
                                    liq_cand = data[k]
                                    l_open = liq_cand['open']
                                    l_high = liq_cand['high']
                                    l_low  = liq_cand['low']
                                    l_num  = liq_cand['candle_number']
                                    
                                    # --- High Liquidation Check ---
                                    if not found_h_liq:
                                        if l_open > triad_h:
                                            if l_low < triad_h: found_h_liq = True
                                        else:
                                            if l_high > triad_h: found_h_liq = True
                                        
                                        if found_h_liq:
                                            triad_candle[f"fvg_{label}_high_liquidated_by_candle_number"] = l_num
                                            liq_cand[f"liquidates_fvg_{label}_high"] = True

                                    # --- Low Liquidation Check ---
                                    if not found_l_liq:
                                        if l_open < triad_l:
                                            if l_high > triad_l: found_l_liq = True
                                        else:
                                            if l_low < triad_l: found_l_liq = True
                                        
                                        if found_l_liq:
                                            triad_candle[f"fvg_{label}_low_liquidated_by_candle_number"] = l_num
                                            liq_cand[f"liquidates_fvg_{label}_low"] = True

                                    if found_h_liq and found_l_liq: 
                                        break

                if swing_count > 0:
                    cv2.imwrite(chart_path, img)
                    config_content[config_key] = data
                    config_content[f"{config_key}_candle_list"] = data 
                    with open(config_path, 'w', encoding='utf-8') as f:
                        json.dump(config_content, f, indent=4)
                    processed_charts += 1
                    total_swings_added += swing_count

            except Exception as e:
                log(f"Error in {sym}/{tf}: {e}", "ERROR")

    return f"Finished. Total Swings: {total_swings_added}, Charts: {processed_charts}"

def liquidity_candles(user_id):
    lagos_tz = pytz.timezone('Africa/Lagos')
    
    def log(msg, level="INFO"):
        ts = datetime.now(lagos_tz).strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{ts}] [{level}] {msg}")

    def resolve_marker(raw):
        if not raw:
            return None, False
        raw = str(raw).lower().strip()
        if raw in ["arrow", "arrows", "singlearrow"]: return "arrow", False
        if raw in ["doublearrow", "doublearrows"]: return "arrow", True
        if raw in ["rightarrow", "right_arrow"]: return "rightarrow", False
        if raw in ["leftarrow", "left_arrow"]: return "leftarrow", False
        if "dot" in raw: return "dot", False
        return raw, False

    log(f"--- STARTING SPACE-BASED LIQUIDITY ANALYSIS: User {user_id} ---")

    dev_dict = load_developers_dictionary() 
    cfg = dev_dict.get(str(user_id))
    if not cfg:
        return f"Error: User {user_id} not in dictionary."
    
    user_root = os.path.join(DEV_PATH, str(user_id))
    ohlc_source_root = os.path.join(user_root, "ohlc")
    am_data = get_account_management(user_id)
    if not am_data:
        return "Error: accountmanagement.json missing."

    define_candles = am_data.get("chart", {}).get("define_candles", {})
    liq_root = define_candles.get("liquidity_candle", {})
    
    total_liq_found = 0

    for apprehend_key, liq_cfg in liq_root.items():
        if not apprehend_key.startswith("apprehend_"): 
            continue
        
        source_def_name = apprehend_key.replace("apprehend_", "")
        source_def = define_candles.get(source_def_name, {})
        if not source_def: 
            continue

        raw_filename = source_def.get("filename", "")
        target_file_filter = raw_filename.replace(".json", "").lower()
        primary_png_name = raw_filename.replace(".json", ".png")

        apprentice_section = liq_cfg.get("liquidity_apprentice_candle", {})
        apprentice_cfg = apprentice_section.get("swing_types", {})
        
        is_bullish = any("higher" in k for k in apprentice_cfg.keys())
        swing_prefix = "higher" if is_bullish else "lower"

        sweeper_section = liq_cfg.get("liquidity_sweeper_candle", {})
        liq_label_at = sweeper_section.get("label_at", {})

        markers = {
            "liq_hh": resolve_marker(liq_label_at.get(f"{swing_prefix}_high_liquidity_candle_marker")),
            "liq_ll": resolve_marker(liq_label_at.get(f"{swing_prefix}_low_liquidity_candle_marker")),
            "liq_hh_txt": liq_label_at.get(f"{swing_prefix}_high_liquidity_candle_text", ""),
            "liq_ll_txt": liq_label_at.get(f"{swing_prefix}_low_liquidity_candle_text", ""),
            "app_hh": resolve_marker(apprentice_cfg.get("label_at", {}).get(f"swing_type_{swing_prefix}_high_marker")),
            "app_ll": resolve_marker(apprentice_cfg.get("label_at", {}).get(f"swing_type_{swing_prefix}_low_marker"))
        }

        for sym in sorted(os.listdir(ohlc_source_root)):
            sym_p = os.path.join(ohlc_source_root, sym)
            if not os.path.isdir(sym_p): 
                continue

            for tf in os.listdir(sym_p):
                tf_p = os.path.join(sym_p, tf)
                if not os.path.isdir(tf_p): 
                    continue
                
                dev_output_dir = os.path.join(user_root, sym, tf)
                config_path = os.path.join(dev_output_dir, "config.json")

                if not os.path.exists(config_path): 
                    continue

                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config_data = json.load(f)

                    config_modified = False
                    
                    for file_key in list(config_data.keys()):
                        if not (file_key.lower() == source_def_name.lower() or 
                                target_file_filter in file_key.lower()):
                            continue

                        entry = config_data[file_key]

                        # ────────────────────────────────────────────────
                        # Only accept direct list of candles
                        # ────────────────────────────────────────────────
                        if not isinstance(entry, list):
                            log(f"Skipping {file_key} — value is not a list (expected direct array of candles)", "WARN")
                            continue

                        candles = entry

                        if len(candles) < 2:
                            log(f"Skipping {file_key} — fewer than 2 candles", "WARN")
                            continue

                        # Optional: basic validation that items look like candles
                        if not all(isinstance(c, dict) for c in candles):
                            log(f"Skipping {file_key} — not all items are dictionaries", "WARN")
                            continue
                        # ────────────────────────────────────────────────

                        png_path = os.path.join(dev_output_dir, f"{file_key}.png")
                        if not os.path.exists(png_path):
                            png_path = os.path.join(dev_output_dir, primary_png_name)

                        img = cv2.imread(png_path)
                        key_modified = False

                        for i in range(len(candles) - 1):
                            base_c = candles[i]
                            next_c = candles[i + 1]
                            
                            b_h = base_c.get("high")
                            b_l = base_c.get("low")
                            n_h = next_c.get("high")
                            n_l = next_c.get("low")
                            
                            if None in [b_h, b_l, n_h, n_l]: 
                                continue

                            target_side = None
                            ref_price = None

                            if n_h >= b_h and n_l <= b_l:
                                continue 
                            
                            elif n_h > b_h and n_l > b_l:
                                target_side = "low"
                                ref_price = b_l
                                
                            elif n_l < b_l and n_h < b_h:
                                target_side = "high"
                                ref_price = b_h
                            
                            else:
                                continue

                            for j in range(i + 2, len(candles)):
                                sweeper_c = candles[j]
                                swept = False

                                if target_side == "low" and sweeper_c.get("low", 999999) <= ref_price:
                                    swept = True
                                    pos = "low"
                                    m_key = "liq_ll"
                                    a_key = "app_ll"
                                elif target_side == "high" and sweeper_c.get("high", 0) >= ref_price:
                                    swept = True
                                    pos = "high"
                                    m_key = "liq_hh"
                                    a_key = "app_hh"

                                if swept:
                                    obj, dbl = markers[m_key]
                                    app_obj, app_dbl = markers[a_key]
                                    txt = markers.get(f"{m_key}_txt", "")
                                    
                                    # ===== FIXED: Preserve ALL existing fields when marking =====
                                    
                                    # Mark the SWEEPER candle - PRESERVE existing fields
                                    # Don't use update() which overwrites everything
                                    # Instead, set individual fields while keeping others
                                    sweeper_c["is_liquidity_sweep"] = True
                                    sweeper_c["liquidity_price"] = ref_price
                                    
                                    # Also track WHICH victim this sweeper swept
                                    # Use a list to track multiple victims if this candle sweeps multiple
                                    if "swept_victims" not in sweeper_c:
                                        sweeper_c["swept_victims"] = []
                                    if base_c.get("candle_number") not in sweeper_c["swept_victims"]:
                                        sweeper_c["swept_victims"].append(base_c.get("candle_number"))
                                    
                                    # Keep the single victim number for backward compatibility
                                    # But only set it if this is the first victim or we want to track the latest
                                    if "swept_victim_number" not in sweeper_c:
                                        sweeper_c["swept_victim_number"] = base_c.get("candle_number")
                                    
                                    # Mark the VICTIM candle - PRESERVE existing fields
                                    base_c["swept_by_liquidity"] = True
                                    base_c["swept_by_candle_number"] = sweeper_c.get("candle_number")
                                    
                                    # Also track ALL sweepers that hit this victim (if multiple)
                                    if "swept_by_candles" not in base_c:
                                        base_c["swept_by_candles"] = []
                                    if sweeper_c.get("candle_number") not in base_c["swept_by_candles"]:
                                        base_c["swept_by_candles"].append(sweeper_c.get("candle_number"))
                                    
                                    # If this victim is ALSO a sweeper (has is_liquidity_sweep already), preserve that
                                    # We don't touch any existing fields, so is_liquidity_sweep remains if it was there
                                    
                                    # Optional: Add a flag to indicate this candle plays both roles
                                    if base_c.get("is_liquidity_sweep") is True:
                                        base_c["is_both_sweeper_and_victim"] = True
                                    
                                    if sweeper_c.get("swept_by_liquidity") is True:
                                        sweeper_c["is_both_sweeper_and_victim"] = True
                                    
                                    # ===== END FIX =====

                                    if img is not None:
                                        label_objects_and_text(img, 
                                            int(sweeper_c.get("candle_x", 0)), 
                                            int(sweeper_c.get("candle_y", 0)), 
                                            int(sweeper_c.get("candle_height", 0)),
                                            custom_text=txt, 
                                            object_type=obj, 
                                            is_bullish_arrow=(target_side == "low"),
                                            is_marked=True, 
                                            double_arrow=dbl, 
                                            arrow_color=(0, 255, 255), 
                                            label_position=pos)
                                        
                                        label_objects_and_text(img, 
                                            int(base_c.get("candle_x", 0)), 
                                            int(base_c.get("candle_y", 0)), 
                                            int(base_c.get("candle_height", 0)),
                                            custom_text="", 
                                            object_type=app_obj, 
                                            is_bullish_arrow=(target_side == "low"),
                                            is_marked=True, 
                                            double_arrow=app_dbl, 
                                            arrow_color=(255, 165, 0), 
                                            label_position=pos)

                                    key_modified = True
                                    config_modified = True
                                    total_liq_found += 1
                                    break 

                        if key_modified and img is not None:
                            cv2.imwrite(png_path, img)

                    if config_modified:
                        with open(config_path, 'w', encoding='utf-8') as f:
                            json.dump(config_data, f, indent=4)

                except Exception as e:
                    log(f"Error processing {sym} ({tf}): {e}", "ERROR")

    log(f"--- LIQUIDITY COMPLETE --- Total Space Sweeps: {total_liq_found}")
    return f"Completed: {total_liq_found} sweeps."

def entry_point_of_interest(user_id):
    lagos_tz = pytz.timezone('Africa/Lagos') 
    
    
    def log(msg, level="INFO"):
        ts = datetime.now(lagos_tz).strftime('%H:%M:%S')
        print(f"[{ts}] {msg}")

    def get_max_candle_count(dev_base_path, timeframe):
        """Helper to find candle count. Returns 0 if config is null or missing."""
        config_path = os.path.join(dev_base_path, "accountmanagement.json")
        max_days = 0  # Default to 0 so missing file/error clears records
        
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # .get("chart", {}) returns empty dict if "chart" is missing
                    # .get("maximum_holding_days") returns None if key is missing or null
                    val = config.get("chart", {}).get("maximum_holding_days")
                    
                    if val is not None:
                        max_days = val
                    else:
                        max_days = 0 # Handle explicit null or missing key
        except Exception:
            max_days = 0 # Fallback on error to ensure clearing logic triggers

        # Conversion map
        tf_map = {
            "1m": 1, "5m": 5, "10m": 10, "15m": 15, "30m": 30,
            "1h": 60, "4h": 240, "1d": 1440
        }
        
        mins_per_candle = tf_map.get(timeframe.lower(), 1)
        total_minutes_in_period = max_days * 24 * 60
        return total_minutes_in_period // mins_per_candle
    
    def mark_paused_symbols_in_full_candles(dev_base_path, new_folder_name):
        paused_folder = os.path.join(dev_base_path, new_folder_name, "paused_symbols_folder")
        paused_file = os.path.join(paused_folder, "paused_symbols.json")
        
        if not os.path.exists(paused_file):
            return

        # --- IMMEDIATE FIX: Global Config Check ---
        # We check a dummy timeframe ('1m') just to see if the user set max_days to 0
        # because if max_days is 0, it's 0 for all timeframes.
        global_threshold = get_max_candle_count(dev_base_path, "1m")
        if global_threshold <= 0:
            try:
                with open(paused_file, 'w', encoding='utf-8') as f:
                    json.dump([], f, indent=4)
                # log("Global threshold is 0: Paused symbols file cleared.")
                return # Exit early so no other logic restores the records
            except Exception as e:
                print(f"Error clearing paused file: {e}")
                return

        # --- Standard logic continues if threshold > 0 ---
        try:
            with open(paused_file, 'r', encoding='utf-8') as f:
                paused_records = json.load(f)
        except Exception as e:
            print(f"Error reading paused symbols: {e}")
            return

        updated_paused_records = []
        records_removed = False
        markers_map = {}

        for record in paused_records:
            sym, tf = record.get("symbol"), record.get("timeframe")
            if sym and tf:
                markers_map.setdefault((sym, tf), []).append(record)

        for (sym, tf), records in markers_map.items():
            max_allowed_count = get_max_candle_count(dev_base_path, tf)
            
            # This part handles specific TF logic if max_allowed_count varies
            if max_allowed_count <= 0:
                records_removed = True
                continue

            full_candle_path = os.path.join(dev_base_path, new_folder_name, sym, f"{tf}_full_candles_data.json")
            
            if not os.path.exists(full_candle_path):
                updated_paused_records.extend(records)
                continue

            try:
                with open(full_candle_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                if not isinstance(data, list) or not data:
                    updated_paused_records.extend(records)
                    continue

                candles = data[1:] if (len(data) > 0 and "summary" in data[0]) else data
                total_candles = len(candles)
                summary = {}
                current_tf_records_to_keep = []

                for rec in records:
                    from_time = rec.get("time")
                    after_data = rec.get("after", {})
                    after_time = after_data.get("time")
                    entry_val = rec.get("entry")
                    order_type = rec.get("order_type")

                    clean_from = from_time.replace(':', '-').replace(' ', '_')
                    clean_after = after_time.replace(':', '-').replace(' ', '_') if after_time else "N/A"
                    
                    should_remove_this_record = False
                    final_count_ahead = 0
                    final_remaining = 0

                    for idx, candle in enumerate(candles):
                        c_time = candle.get("time")
                        if c_time == from_time:
                            candle[f"from_{clean_from}"] = True
                            candle["entry"] = entry_val
                            candle["order_type"] = order_type

                        if after_time and c_time == after_time:
                            count_ahead = total_candles - (idx + 1)
                            remaining = max_allowed_count - count_ahead
                            final_count_ahead = count_ahead
                            final_remaining = remaining

                            if count_ahead >= max_allowed_count:
                                should_remove_this_record = True
                                records_removed = True
                            
                            candle[f"after_{clean_after}"] = True
                            candle[f"connected_with_{clean_from}"] = True
                            candle["candles_count_ahead_after_candle"] = count_ahead
                            candle["remaining_candles_to_threshold"] = remaining

                    if not should_remove_this_record:
                        current_tf_records_to_keep.append(rec)
                        conn_idx = len(current_tf_records_to_keep)
                        summary[f"connection_{conn_idx}"] = {
                            f"from_{clean_from}": entry_val,
                            "order_type": order_type,
                            "after_time": after_time,
                            "candles_count_ahead_after_candle": final_count_ahead,
                            "remaining_candles_to_threshold": final_remaining
                        }

                final_output = [{"summary": summary}] + candles
                with open(full_candle_path, 'w', encoding='utf-8') as f:
                    json.dump(final_output, f, indent=4)
                
                updated_paused_records.extend(current_tf_records_to_keep)

            except Exception as e:
                print(f"Error processing {sym} {tf}: {e}")
                updated_paused_records.extend(records)

        if records_removed:
            with open(paused_file, 'w', encoding='utf-8') as f:
                json.dump(updated_paused_records, f, indent=4)

    def cleanup_non_paused_symbols(dev_base_path, new_folder_name):
        """
        Deletes all symbol folders in the new_folder_name directory that are 
        NOT present in the paused_symbols.json file.
        """
        target_dir = os.path.join(dev_base_path, new_folder_name)
        paused_file = os.path.join(target_dir, "paused_symbols_folder", "paused_symbols.json")
        
        if not os.path.exists(target_dir):
            return

        # 1. Identify which symbols are paused
        paused_symbols = set()
        if os.path.exists(paused_file):
            try:
                with open(paused_file, 'r', encoding='utf-8') as f:
                    paused_records = json.load(f)
                    paused_symbols = {rec.get("symbol") for rec in paused_records if rec.get("symbol")}
            except Exception as e:
                log(f"Error reading paused symbols during cleanup: {e}")
                return

        # 2. Iterate through folders and delete if not in the paused list
        # We skip 'paused_symbols_folder' itself and any files (like logs)
        for item in os.listdir(target_dir):
            item_path = os.path.join(target_dir, item)
            
            # We only care about directories that represent symbols
            if os.path.isdir(item_path) and item != "paused_symbols_folder":
                if item not in paused_symbols:
                    try:
                        shutil.rmtree(item_path)
                        # log(f"Cleaned up non-paused symbol folder: {item}")
                    except Exception as e:
                        log(f"Failed to delete folder {item}: {e}")

    def identify_paused_symbols_poi(dev_base_path, new_folder_name):
        """
        Analyzes full_candles_data.json to find price violations (hitler candles)
        for paused records. Removes symbols from paused list when violation is found.
        """
        paused_folder = os.path.join(dev_base_path, new_folder_name, "paused_symbols_folder")
        paused_file = os.path.join(paused_folder, "paused_symbols.json")
        
        if not os.path.exists(paused_file):
            return

        try:
            with open(paused_file, 'r', encoding='utf-8') as f:
                paused_records = json.load(f)
        except Exception as e:
            log(f"Error reading paused symbols for POI: {e}")
            return

        # Group by symbol/tf to minimize file I/O
        markers_map = {}
        for record in paused_records:
            sym, tf = record.get("symbol"), record.get("timeframe")
            if sym and tf:
                markers_map.setdefault((sym, tf), []).append(record)

        updated_paused_records = []  # Will hold records that should remain paused
        records_removed = False

        for (sym, tf), records in markers_map.items():
            full_candle_path = os.path.join(dev_base_path, new_folder_name, sym, f"{tf}_full_candles_data.json")
            
            if not os.path.exists(full_candle_path):
                updated_paused_records.extend(records)
                continue

            try:
                with open(full_candle_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                if not isinstance(data, list) or len(data) < 2:
                    updated_paused_records.extend(records)
                    continue

                # Separate summary and candles
                summary_obj = data[0].get("summary", {})
                candles = data[1:]
                
                modified_summary = False
                records_to_keep_for_this_symbol = []  # Records that didn't trigger hitler

                # Process each connection defined in the summary
                for conn_key, conn_val in summary_obj.items():
                    # Extract 'after_time' and 'order_type' to determine logic
                    after_time = conn_val.get("after_time")
                    order_type = conn_val.get("order_type")
                    
                    # Find the 'from' key to get the entry price
                    from_key = next((k for k in conn_val.keys() if k.startswith("from_")), None)
                    if not from_key or not after_time:
                        records_to_keep_for_this_symbol.append(conn_val)  # Keep if incomplete data
                        continue
                    
                    entry_price = conn_val[from_key]
                    hitler_found = False

                    # Search for price violation after the 'after' candle
                    search_active = False
                    for candle in candles:
                        c_time = candle.get("time")
                        
                        if not search_active:
                            if c_time == after_time:
                                search_active = True
                            continue
                        
                        c_num = candle.get("candle_number", "unknown")
                        
                        if "buy" in order_type.lower():
                            low_val = candle.get("low")
                            if low_val is not None and low_val < entry_price:
                                label = f"hitlercandle{c_num}_ahead_after_candle_breaches_from_low_price_{entry_price}"
                                conn_val[label] = True
                                hitler_found = True
                                records_removed = True  # Mark for removal from paused list
                                break
                        
                        elif "sell" in order_type.lower():
                            high_val = candle.get("high")
                            if high_val is not None and high_val > entry_price:
                                label = f"hitlercandle{c_num}_ahead_after_candle_breaches_from_high_price_{entry_price}"
                                conn_val[label] = True
                                hitler_found = True
                                records_removed = True  # Mark for removal from paused list
                                break

                    if not hitler_found:
                        conn_val["no_hitler"] = True
                        # Find and keep the original paused record that matches this connection
                        matching_record = next(
                            (r for r in records if r.get("after", {}).get("time") == after_time),
                            None
                        )
                        if matching_record:
                            records_to_keep_for_this_symbol.append(matching_record)
                    
                    modified_summary = True

                # Add records that should remain paused to the global list
                updated_paused_records.extend(records_to_keep_for_this_symbol)

                # Save the updated candles with hitler markers
                if modified_summary:
                    data[0]["summary"] = summary_obj
                    with open(full_candle_path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=4)

            except Exception as e:
                log(f"Error in identify_paused_symbols_poi for {sym} {tf}: {e}")
                updated_paused_records.extend(records)  # Keep records on error

        # Update paused file if any records were removed
        if records_removed:
            with open(paused_file, 'w', encoding='utf-8') as f:
                json.dump(updated_paused_records, f, indent=4)
            log(f"Removed {len(paused_records) - len(updated_paused_records)} symbols from paused list due to price violations")

    def swing_points_liquidity(target_data_tf, new_key, original_candles, identify_config):
        """
        Identifies liquidity sweepers directly from original candles.
        For Lower Low: finds first candle with low lower than the definition's low
        For Higher High: finds first candle with high higher than the definition's high
        Marks both victims and sweepers directly on the original candle records.
        
        Victim gets marked with:
            - swept_by_liquidity: true
            - swept_by_candle_number: [sweeper candle number]
            - swept_by_candles: [list of sweeper candle numbers]
        
        Sweeper gets marked with:
            - is_liquidity_sweep: true
            - swept_victims: [list of victim candle numbers]
            - swept_victim_number: [first/primary victim]
        """
        if not identify_config or not isinstance(target_data_tf, dict) or not original_candles:
            return
        
        # First, identify all definition/victim candles (swing_lows and swing_highs)
        victims = []  # List of (candle_number, swing_type, target_price)
        
        for candle in original_candles:
            if not isinstance(candle, dict):
                continue
                
            swing_type = candle.get("swing_type", "").lower()
            candle_num = candle.get("candle_number")
            
            if not swing_type or candle_num is None:
                continue
            
            # Only consider swing_low and swing_high as potential victims
            if swing_type == "swing_low":
                target_price = candle.get("low")
                if target_price is not None:
                    victims.append((candle_num, swing_type, target_price))
                    #log(f"    📍 Found victim candidate: Candle {candle_num} | Type: swing_low | Price: {target_price:.5f}")
                    
            elif swing_type == "swing_high":
                target_price = candle.get("high")
                if target_price is not None:
                    victims.append((candle_num, swing_type, target_price))
                    #log(f"    📍 Found victim candidate: Candle {candle_num} | Type: swing_high | Price: {target_price:.5f}")
        
        
        #log(f"  🔍 LIQUIDITY SWEEP: Found {len(victims)} victim candles to check for sweepers")
        
        # Track relationships
        sweeper_to_victims = {}  # sweeper_num -> list of victim_nums
        victim_to_sweepers = {}  # victim_num -> list of sweeper_nums
        
        # For each victim, find its sweeper
        for victim_num, swing_type, target_price in victims:
            
            # Find the FIRST candle after the victim that sweeps it
            sweeper_num = None
            
            for candle in original_candles:
                if not isinstance(candle, dict):
                    continue
                    
                candle_num = candle.get("candle_number")
                if candle_num is None or candle_num <= victim_num:
                    continue
                
                if swing_type == "swing_low":
                    candle_price = candle.get("low")
                    if candle_price is not None and candle_price < target_price:
                        sweeper_num = candle_num
                        #log(f"      ✅ Sweeper found: Candle {candle_num} low ({candle_price:.5f}) < victim low ({target_price:.5f})")
                        break
                        
                elif swing_type == "swing_high":
                    candle_price = candle.get("high")
                    if candle_price is not None and candle_price > target_price:
                        sweeper_num = candle_num
                        #log(f"      ✅ Sweeper found: Candle {candle_num} high ({candle_price:.5f}) > victim high ({target_price:.5f})")
                        break
            
            if sweeper_num:
                # Record relationship
                if sweeper_num not in sweeper_to_victims:
                    sweeper_to_victims[sweeper_num] = []
                if victim_num not in sweeper_to_victims[sweeper_num]:
                    sweeper_to_victims[sweeper_num].append(victim_num)
                
                if victim_num not in victim_to_sweepers:
                    victim_to_sweepers[victim_num] = []
                if sweeper_num not in victim_to_sweepers[victim_num]:
                    victim_to_sweepers[victim_num].append(sweeper_num)
                
                #log(f"      📝 Relationship: Victim {victim_num} <- Sweeper {sweeper_num}")
        
        # Mark the original candles
        victims_marked = 0
        sweepers_marked = 0
        
        # Mark victims
        for victim_num, sweeper_list in victim_to_sweepers.items():
            for candle in original_candles:
                if isinstance(candle, dict) and candle.get("candle_number") == victim_num:
                    candle["swept_by_liquidity"] = True
                    candle["swept_by_candle_number"] = sweeper_list[0]
                    candle["swept_by_candles"] = sweeper_list
                    victims_marked += 1
                    #log(f"    🎯 Marked victim candle {victim_num} swept by: {sweeper_list}")
                    break
        
        # Mark sweepers
        for sweeper_num, victim_list in sweeper_to_victims.items():
            for candle in original_candles:
                if isinstance(candle, dict) and candle.get("candle_number") == sweeper_num:
                    candle["is_liquidity_sweep"] = True
                    candle["swept_victims"] = victim_list
                    candle["swept_victim_number"] = victim_list[0]
                    sweepers_marked += 1
                    #log(f"    💧 Marked sweeper candle {sweeper_num} sweeping victims: {victim_list}")
                    break
        
        #log(f"  ✅ LIQUIDITY SWEEP: Found {len(sweeper_to_victims)} sweepers, marked {victims_marked} victims and {sweepers_marked} sweepers for {new_key}")
    
    def sanitize_pattern_definitions(patterns_dict):
        """
        Sanitizes each pattern in the dictionary.
        Ensures that the N-th candle in a pattern family only contains 'define_N' metadata.
        """
        if not patterns_dict:
            return {}

        sanitized_patterns = {}

        for p_name, family in patterns_dict.items():
            new_family = []
            
            # The family is ordered [define_1, define_2, ..., define_max]
            for idx, candle in enumerate(family):
                if not isinstance(candle, dict):
                    new_family.append(candle)
                    continue
                
                # Create a shallow copy to avoid modifying the original list in-place
                clean_candle = candle.copy()
                current_rank = idx + 1  # 1-based indexing for define_n
                
                # Identify keys to keep:
                # 1. Standard OHLCV and technical data
                # 2. 'define_N' keys specific to this candle's position in the pattern
                keys_to_delete = []
                
                for key in clean_candle.keys():
                    # If the key is a 'define_X' key
                    if key.startswith("define_"):
                        # Extract the number from 'define_N...'
                        try:
                            parts = key.split('_')
                            def_num = int(parts[1])
                            
                            # Logic: If this is the 2nd candle in the list, 
                            # it should ONLY have define_2 related keys.
                            if def_num != current_rank:
                                keys_to_delete.append(key)
                        except (ValueError, IndexError):
                            continue
                
                # Remove the non-relevant define keys
                for k in keys_to_delete:
                    del clean_candle[k]
                    
                new_family.append(clean_candle)
                
            sanitized_patterns[p_name] = new_family
            
        return sanitized_patterns
   
    def identify_definitions(candle_data, identify_config, source_def_name, raw_filename_base):
        if not identify_config:
            return candle_data
            
        processed_data = candle_data.copy()
        
        # Ordinal mapping for naming convention
        ordinals = ["zero", "first", "second", "third", "fourth", "fifth", "sixth", 
                    "seventh", "eighth", "ninth", "tenth", "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth", "seventeenth", "eighteenth", "nineteenth", "twenteenth"]

        # Sort definitions to ensure sequential processing (define_1, define_2...)
        definitions = sorted([(k, v) for k, v in identify_config.items() 
                            if k.startswith("define_")], 
                            key=lambda x: int(x[0].split('_')[1]))
        
        if not definitions:
            return processed_data

        def get_target_swing(current_type, logic_type):
            logic_type = logic_type.lower()
            if "opposite" in logic_type:
                return "swing_low" if current_type == "swing_high" else "swing_high"
            if "identical" in logic_type:
                return current_type
            return None

        for file_key, candles in processed_data.items():
            if not isinstance(candles, list): continue
            
            # --- GLOBAL LOOP: Every swing candle gets a turn to be the 'Anchor' (define_1) ---
            for i, anchor_candle in enumerate(candles):
                if not (isinstance(anchor_candle, dict) and "swing_type" in anchor_candle):
                    continue
                    
                s_type = anchor_candle.get("swing_type", "").lower()
                if s_type not in ["swing_high", "swing_low"]:
                    continue

                # Step 1: Initialize the chain with define_1
                def1_name = definitions[0][0]
                anchor_candle[def1_name] = True
                anchor_candle[f"{def1_name}_swing_type"] = s_type
                anchor_idx = anchor_candle.get("candle_number", i)
                
                # chain_history tracks the 'firstfound' of each step to determine the NEXT step's start point
                # Format: { def_name: (index_in_list, candle_object) }
                chain_history = {def1_name: (i, anchor_candle)}

                # Step 2: Process subsequent definitions (The Chain)
                for def_idx in range(1, len(definitions)):
                    curr_def_name, curr_def_config = definitions[def_idx]
                    prev_def_name, _ = definitions[def_idx - 1]
                    
                    # Logic dictates we start searching AFTER the 'firstfound' of the previous definition
                    if prev_def_name not in chain_history:
                        break
                    
                    prev_idx_in_list, prev_candle_obj = chain_history[prev_def_name]
                    search_start_idx = prev_idx_in_list + 1
                    
                    prev_swing_type = prev_candle_obj.get(f"{prev_def_name}_swing_type", "")
                    target_swing = get_target_swing(prev_swing_type, curr_def_config.get("type", ""))
                    
                    if not target_swing:
                        continue

                    found_count_for_this_step = 0
                    
                    # Search forward for ALL matches
                    for j in range(search_start_idx, len(candles)):
                        target_candle = candles[j]
                        if not (isinstance(target_candle, dict) and target_candle.get("swing_type")):
                            continue
                        
                        if target_candle["swing_type"].lower() == target_swing:
                            found_count_for_this_step += 1
                            curr_candle_num = target_candle.get("candle_number", j)
                            ref_candle_num = prev_candle_obj.get("candle_number", prev_idx_in_list)
                            
                            # Mark Base Flags
                            target_candle[curr_def_name] = True
                            target_candle[f"{curr_def_name}_swing_type"] = target_swing
                            
                            # Determine Ordinal (firstfound, secondfound, etc.)
                            if found_count_for_this_step < len(ordinals):
                                ord_str = f"{ordinals[found_count_for_this_step]}found"
                            else:
                                ord_str = f"{found_count_for_this_step}thfound"
                            
                            # Construct Dynamic Key
                            # e.g., define_2_firstfound_4_in_connection_with_define_1_1
                            conn_key = f"{curr_def_name}_{ord_str}_{curr_candle_num}_in_connection_with_{prev_def_name}_{ref_candle_num}"
                            
                            logic_label = "opposite" if "opposite" in curr_def_config.get("type", "").lower() else "identical"
                            target_candle[conn_key] = logic_label
                            
                            # If this is the FIRST one found for this step, 
                            # it becomes the anchor for the NEXT definition (define_N+1)
                            if found_count_for_this_step == 1:
                                chain_history[curr_def_name] = (j, target_candle)

                    # If no matches were found for this step, the chain for this anchor is broken
                    if found_count_for_this_step == 0:
                        break

        return processed_data

    def apply_definitions_condition(candles, identify_config, new_filename_value, file_key):
        if not identify_config or not isinstance(candles, list):
            return candles, {}

        # --- SECTION 1: DYNAMIC VALIDATION (The "Logic Check") ---
        for target_candle in candles:
            if not isinstance(target_candle, dict): continue
            conn_keys = [k for k in target_candle.keys() if "_in_connection_with_" in k]
            
            for conn_key in conn_keys:
                parts = conn_key.split('_')
                curr_def_base = f"{parts[0]}_{parts[1]}" 
                
                def_cfg = identify_config.get(curr_def_base, {})
                condition_cfg = def_cfg.get("condition", "").lower()
                if not condition_cfg: 
                    target_candle[f"{conn_key}_met"] = True
                    continue

                mode = "behind" if "behind" in condition_cfg else "beyond"
                target_match = re.search(r'define_(\d+)', condition_cfg)
                if not target_match: continue
                target_def_index = int(target_match.group(1))

                # Trace back to find the specific define_n ref candle
                ref_candle = None
                search_key = conn_key
                while True:
                    t_parts = search_key.split('_')
                    p_def_lvl = int(t_parts[8])
                    p_num = int(t_parts[9])
                    
                    if p_def_lvl == target_def_index:
                        ref_candle = next((c for c in candles if c.get("candle_number") == p_num), None)
                        break
                    
                    parent_candle = next((c for c in candles if c.get("candle_number") == p_num), None)
                    if not parent_candle: break
                    search_key = next((k for k in parent_candle.keys() if k.startswith(f"define_{p_def_lvl}_") and "_in_connection_" in k), None)
                    if not search_key: break

                if ref_candle:
                    ref_h, ref_l = ref_candle.get("high"), ref_candle.get("low")
                    r_type = ref_candle.get("swing_type", "").lower()
                    
                    # Helper function for the core price logic
                    def check_logic(c_type, c_h, c_l, r_type, r_h, r_l, mode):
                        if mode == "behind":
                            if c_type == "swing_high" and r_type == "swing_high": return c_h < r_h
                            if c_type == "swing_low" and r_type == "swing_low": return c_l > r_l
                            if c_type == "swing_high" and r_type == "swing_low": return c_l > r_h
                            if c_type == "swing_low" and r_type == "swing_high": return c_h < r_l
                        elif mode == "beyond":
                            if c_type == "swing_high" and r_type == "swing_high": return c_h > r_h
                            if c_type == "swing_low" and r_type == "swing_low": return c_l < r_l
                            if c_type == "swing_high" and r_type == "swing_low": return c_h > r_h
                            if c_type == "swing_low" and r_type == "swing_high": return c_l < r_l
                        return False

                    # 1. Check the target candle itself
                    curr_h, curr_l = target_candle.get("high"), target_candle.get("low")
                    c_type = target_candle.get("swing_type", "").lower()
                    
                    logic_met = check_logic(c_type, curr_h, curr_l, r_type, ref_h, ref_l, mode)

                    if logic_met:
                        target_candle[f"{conn_key}_met"] = True

        # --- SECTION 2: EXTRACTION (The "Grouping") ---
        def_nums = [int(k.split('_')[1]) for k in identify_config.keys() if k.startswith("define_")]
        max_def = max(def_nums) if def_nums else 0
        patterns_dict = {}
        pattern_idx = 1

        for candle in candles:
            if not isinstance(candle, dict): continue
            last_def_keys = [k for k in candle.keys() if k.startswith(f"define_{max_def}_") and k.endswith("_met")]
            for m_key in last_def_keys:
                current_family = [candle]
                is_valid_family = True
                current_trace_key = m_key
                for d in range(max_def, 1, -1):
                    p_parts = current_trace_key.split('_')
                    parent_num = int(p_parts[9])
                    parent_def_lvl = int(p_parts[8])
                    parent_candle = next((c for c in candles if c.get("candle_number") == parent_num), None)
                    if not parent_candle:
                        is_valid_family = False
                        break
                    if parent_def_lvl > 1:
                        parent_met_key = next((k for k in parent_candle.keys() if k.startswith(f"define_{parent_def_lvl}_") and k.endswith("_met")), None)
                        if not parent_met_key:
                            is_valid_family = False
                            break
                        current_trace_key = parent_met_key
                    current_family.insert(0, parent_candle)

                if is_valid_family:
                    unique_family = []
                    seen_nums = set()
                    for c in current_family:
                        if c['candle_number'] not in seen_nums:
                            unique_family.append(c)
                            seen_nums.add(c['candle_number'])
                    patterns_dict[f"pattern_{pattern_idx}"] = unique_family
                    pattern_idx += 1

        patterns_dict = sanitize_pattern_definitions(patterns_dict)
        patterns_dict = apply_optional_extreme(patterns_dict, identify_config, candles)
        
        # --- SECTION 3: FINAL PATTERN VALIDATION ---
        validated_patterns = {}
        
        # Build lookup for original candles by candle_number for neighbor checks
        original_candle_lookup = {}
        for candle in candles:
            if isinstance(candle, dict) and candle.get('candle_number') is not None:
                original_candle_lookup[candle['candle_number']] = candle
        
        for pattern_key, pattern_candles in patterns_dict.items():
            if not pattern_candles:
                continue
                
            pattern_valid = True
            
            # Collect definition candles
            definition_candles = {}
            for candle in pattern_candles:
                for key in candle.keys():
                    if key.startswith("define_") and candle[key] is True:
                        try:
                            parts = key.split('_')
                            if len(parts) >= 2 and parts[1].isdigit():
                                def_num = int(parts[1])
                                if def_num not in definition_candles:
                                    definition_candles[def_num] = candle
                        except (ValueError, IndexError):
                            continue
            
            sorted_def_nums = sorted(definition_candles.keys())
            
            # Check each definition's conditions
            for def_num in sorted_def_nums:
                if def_num == 1:
                    continue
                    
                def_cfg = identify_config.get(f"define_{def_num}", {})
                condition_cfg = def_cfg.get("condition", "").lower()
                min_collective = def_cfg.get("minimum_collectivebeyondcandles")
                
                if not condition_cfg:
                    continue
                
                # Parse condition
                mode = "behind" if "behind" in condition_cfg else "beyond"
                target_match = re.search(r'define_(\d+)', condition_cfg)
                if not target_match:
                    continue
                    
                ref_def_num = int(target_match.group(1))
                
                current_candle = definition_candles.get(def_num)
                ref_candle = definition_candles.get(ref_def_num)
                
                if not current_candle or not ref_candle:
                    pattern_valid = False
                    continue
                
                # Get prices and types
                curr_h, curr_l = current_candle.get("high"), current_candle.get("low")
                curr_type = current_candle.get("swing_type", "").lower()
                
                ref_h, ref_l = ref_candle.get("high"), ref_candle.get("low")
                ref_type = ref_candle.get("swing_type", "").lower()
                
                # Check if we need to validate collective beyond candles
                if min_collective and mode == "beyond" and min_collective >= 1:
                    # Get the current candle's number to find neighbors in original candles
                    current_candle_num = current_candle.get('candle_number')
                    
                    if current_candle_num is not None:
                        # Calculate left and right distribution
                        # Give most search to left, least to right
                        left_count = min_collective // 2 + (min_collective % 2)  # Ceiling division for left
                        right_count = min_collective // 2  # Floor division for right
                        
                        # Collect neighbor candles from the original candles list
                        neighbor_candles = []
                        neighbor_candle_numbers = []
                        
                        # Get left neighbors
                        for offset in range(1, left_count + 1):
                            neighbor_num = current_candle_num - offset
                            neighbor = original_candle_lookup.get(neighbor_num)
                            if neighbor:
                                neighbor_candles.append(neighbor)
                                neighbor_candle_numbers.append(neighbor_num)
                        
                        # Get right neighbors
                        for offset in range(1, right_count + 1):
                            neighbor_num = current_candle_num + offset
                            neighbor = original_candle_lookup.get(neighbor_num)
                            if neighbor:
                                neighbor_candles.append(neighbor)
                                neighbor_candle_numbers.append(neighbor_num)
                        
                        # Check each neighbor individually
                        all_neighbors_valid = True
                        
                        for neighbor in neighbor_candles:
                            # Get neighbor's price (high or low based on current candle's swing type)
                            if "high" in curr_type:
                                neighbor_price = neighbor.get("high")
                            else:
                                neighbor_price = neighbor.get("low")
                            
                            if neighbor_price is None:
                                all_neighbors_valid = False
                                break
                            
                            # Check if this neighbor is beyond the reference
                            # Use the same swing type as the current candle for the neighbor
                            neighbor_valid = False
                            
                            if mode == "beyond":
                                if "high" in curr_type:
                                    # For swing high: check if neighbor high > ref high
                                    if "high" in ref_type:
                                        neighbor_valid = neighbor_price > ref_h
                                    elif "low" in ref_type:
                                        neighbor_valid = neighbor_price > ref_h
                                elif "low" in curr_type:
                                    # For swing low: check if neighbor low < ref low
                                    if "low" in ref_type:
                                        neighbor_valid = neighbor_price < ref_l
                                    elif "high" in ref_type:
                                        neighbor_valid = neighbor_price < ref_l
                            
                            if not neighbor_valid:
                                all_neighbors_valid = False
                                break
                        
                        # If neighbors check fails, pattern is invalid
                        if not all_neighbors_valid:
                            pattern_valid = False
                            continue
                        
                        # Also check the current candle itself
                        def check_logic(c_type, c_h, c_l, r_type, r_h, r_l, mode):
                            if mode == "behind":
                                if c_type == "swing_high" and r_type == "swing_high": return c_h < r_h
                                if c_type == "swing_low" and r_type == "swing_low": return c_l > r_l
                                if c_type == "swing_high" and r_type == "swing_low": return c_l > r_h
                                if c_type == "swing_low" and r_type == "swing_high": return c_h < r_l
                            elif mode == "beyond":
                                if c_type == "swing_high" and r_type == "swing_high": return c_h > r_h
                                if c_type == "swing_low" and r_type == "swing_low": return c_l < r_l
                                if c_type == "swing_high" and r_type == "swing_low": return c_h > r_h
                                if c_type == "swing_low" and r_type == "swing_high": return c_l < r_l
                            return False
                        
                        logic_met = check_logic(curr_type, curr_h, curr_l, ref_type, ref_h, ref_l, mode)
                        
                        if not logic_met:
                            pattern_valid = False
                    else:
                        pattern_valid = False
                else:
                    # Standard validation without collective candles
                    def check_logic(c_type, c_h, c_l, r_type, r_h, r_l, mode):
                        if mode == "behind":
                            if c_type == "swing_high" and r_type == "swing_high": return c_h < r_h
                            if c_type == "swing_low" and r_type == "swing_low": return c_l > r_l
                            if c_type == "swing_high" and r_type == "swing_low": return c_l > r_h
                            if c_type == "swing_low" and r_type == "swing_high": return c_h < r_l
                        elif mode == "beyond":
                            if c_type == "swing_high" and r_type == "swing_high": return c_h > r_h
                            if c_type == "swing_low" and r_type == "swing_low": return c_l < r_l
                            if c_type == "swing_high" and r_type == "swing_low": return c_h > r_h
                            if c_type == "swing_low" and r_type == "swing_high": return c_l < r_l
                        return False
                    
                    logic_met = check_logic(curr_type, curr_h, curr_l, ref_type, ref_h, ref_l, mode)
                    
                    if not logic_met:
                        pattern_valid = False
            
            if pattern_valid:
                validated_patterns[pattern_key] = pattern_candles
        
        patterns_dict = validated_patterns
        return candles, patterns_dict
    
    def apply_optional_extreme(patterns_dict, identify_config, all_candles):
        """
        For definitions with find_optional_extreme=True, find more extreme candles
        between current definition and next definition (or to the end if no next definition)
        Using the ORIGINAL full candle data (all_candles) to search for extreme candles,
        not just the limited pattern data.
        """
        if not patterns_dict or not identify_config:
            return patterns_dict
        
        # Find which definitions have optional extreme enabled
        extreme_defs = {}
        for def_key, def_config in identify_config.items():
            if def_config.get("find_optional_extreme") is True:
                # Extract definition number (e.g., "define_3" -> 3)
                def_num = int(def_key.split('_')[1])
                extreme_defs[def_num] = def_config
        
        if not extreme_defs:
            return patterns_dict
        
        
        # Build a quick lookup dictionary for all candles by candle_number
        candle_lookup = {candle.get('candle_number'): candle for candle in all_candles if isinstance(candle, dict) and candle.get('candle_number')}
        
        # Process each pattern
        for pattern_key, pattern_candles in patterns_dict.items():
            if not pattern_candles:
                continue
            
            
            # First, collect ALL definition candles from the pattern
            all_definition_candles = {}  # def_num -> {'candle': candle, 'index': index, 'candle_number': num}
            
            for i, candle in enumerate(pattern_candles):
                for key in candle.keys():
                    if key.startswith("define_") and candle[key] is True:
                        try:
                            parts = key.split('_')
                            if len(parts) >= 2 and parts[1].isdigit():
                                def_num = int(parts[1])
                                if def_num not in all_definition_candles:
                                    all_definition_candles[def_num] = {
                                        'candle': candle,
                                        'index': i,
                                        'candle_number': candle.get('candle_number')
                                    }
                        except (ValueError, IndexError):
                            continue
            
            if not all_definition_candles:
                print("  No definition candles found in pattern")
                continue
            
            # Filter to only definitions that have extreme enabled
            definition_candles = {}
            for def_num in extreme_defs.keys():
                if def_num in all_definition_candles:
                    definition_candles[def_num] = all_definition_candles[def_num]
            
            if not definition_candles:
                continue
            
            # Sort definition numbers to process in order
            sorted_def_nums = sorted(definition_candles.keys())
            
            # For each definition that needs extreme substitution
            for def_num in sorted_def_nums:
                def_config = extreme_defs[def_num]
                def_info = definition_candles[def_num]
                def_candle = def_info['candle']
                def_candle_index = def_info['index']
                def_candle_number = def_info['candle_number']
                
                # Find the next definition that exists in this pattern (ANY definition)
                next_def_num = None
                next_def_candle_number = None
                next_def_index = None
                
                all_sorted_nums = sorted(all_definition_candles.keys())
                for higher_def in all_sorted_nums:
                    if higher_def > def_num:
                        next_def_num = higher_def
                        next_def_candle_number = all_definition_candles[higher_def]['candle_number']
                        next_def_index = all_definition_candles[higher_def]['index']
                        break
                
                # Determine search range using candle numbers in the ORIGINAL data
                start_candle_number = def_candle_number + 1
                end_candle_number = next_def_candle_number - 1 if next_def_candle_number else float('inf')
                
                
                # Get current candle's swing type and price
                swing_type = def_candle.get("swing_type", "").lower()
                is_swing_high = "high" in swing_type
                is_swing_low = "low" in swing_type
                
                if not is_swing_high and not is_swing_low:
                    continue
                
                current_price = def_candle.get("high") if is_swing_high else def_candle.get("low")
                
                # Find the most extreme candle in the ORIGINAL candle data
                extreme_candidate = None
                extreme_price = current_price
                extreme_candle_number = None
                
                # Get all candles in range from the lookup
                max_candle_num = max(candle_lookup.keys()) if candle_lookup else 0
                for candle_num in range(start_candle_number, int(end_candle_number) + 1 if next_def_candle_number else max_candle_num + 1):
                    candle = candle_lookup.get(candle_num)
                    if not candle:
                        continue
                    
                    # Only consider candles of the same swing type
                    candle_swing_type = candle.get("swing_type", "").lower()
                    
                    if is_swing_high and "high" in candle_swing_type:
                        # Look for higher high
                        candle_high = candle.get("high")
                        if candle_high and candle_high > extreme_price:
                            extreme_price = candle_high
                            extreme_candidate = candle
                            extreme_candle_number = candle_num
                    
                    elif is_swing_low and "low" in candle_swing_type:
                        # Look for lower low
                        candle_low = candle.get("low")
                        if candle_low and candle_low < extreme_price:
                            extreme_price = candle_low
                            extreme_candidate = candle
                            extreme_candle_number = candle_num
                
                # If we found a more extreme candle
                if extreme_candidate is not None:
                    
                    # NOW we need to find or create this candle in the pattern
                    # Check if extreme candle already exists in pattern
                    extreme_in_pattern_idx = None
                    for i, c in enumerate(pattern_candles):
                        if c.get('candle_number') == extreme_candle_number:
                            extreme_in_pattern_idx = i
                            extreme_candidate = c  # Use the pattern's version
                            break
                    
                    # Define the base fields that should be kept in the candle
                    base_candle_fields = [
                        "open", "high", "low", "close", "volume", "spread", 
                        "real_volume", "symbol", "time", "candle_number", "timeframe",
                        "candle_x", "candle_y", "candle_width", "candle_height",
                        "candle_left", "candle_right", "candle_top", "candle_bottom",
                        "swing_type", "is_swing", "active_color", "draw_x", "draw_y",
                        "draw_w", "draw_h", "draw_left", "draw_right", "draw_top", 
                        "draw_bottom", "m_idx"
                    ]
                    
                    # Also keep swept_by related fields if they exist
                    swept_fields = ["swept_by_liquidity", "swept_by_candle_number", "swept_by_candles"]
                    
                    if extreme_in_pattern_idx is None:
                        # Extreme candle not in pattern yet - we need to add it
                        # First, determine where to insert it (between def_candle and next_def)
                        insert_idx = def_candle_index + 1
                        
                        # Create a clean candle with only the base fields
                        import copy
                        new_candle = {}
                        
                        # Copy only the base fields from the extreme candidate
                        for field in base_candle_fields + swept_fields:
                            if field in extreme_candidate:
                                new_candle[field] = extreme_candidate[field]
                        
                        # Insert it into the pattern
                        pattern_candles.insert(insert_idx, new_candle)
                        extreme_candidate = new_candle
                        extreme_in_pattern_idx = insert_idx
                        
                        # Update indices in all_definition_candles for definitions after insertion point
                        for other_def_num, other_info in all_definition_candles.items():
                            if other_info['index'] >= insert_idx:
                                other_info['index'] += 1
                        
                        # Also update next_def_index if it exists
                        if next_def_index is not None and next_def_index >= insert_idx:
                            next_def_index += 1
                    else:
                        # Extreme candle already exists in pattern
                        # Clean the existing candle to remove any extra flags
                        cleaned_candle = {}
                        for field in base_candle_fields + swept_fields:
                            if field in extreme_candidate:
                                cleaned_candle[field] = extreme_candidate[field]
                        
                        # Replace the candle in the pattern with the cleaned version
                        pattern_candles[extreme_in_pattern_idx] = cleaned_candle
                        extreme_candidate = cleaned_candle
                    
                    # Collect all define_{def_num} related flags from the original candle
                    keys_to_transfer = []
                    for key in list(def_candle.keys()):
                        if key.startswith(f"define_{def_num}"):
                            keys_to_transfer.append(key)
                    
                    # Also collect other important keys that should be transferred
                    additional_keys = ["pattern_entry", "from", "after", "drawn_and_stopped_on_hitler210"]
                    for key in additional_keys:
                        if key in def_candle:
                            keys_to_transfer.append(key)
                    
                    # Remove these keys from original candle
                    for key in keys_to_transfer:
                        if key in def_candle:
                            del def_candle[key]
                    
                    # Add them to extreme candle
                    for key in keys_to_transfer:
                        extreme_candidate[key] = def_candle.get(key, True)
                    
                    # Mark that substitution happened (this is the only extra flag we add)
                    extreme_candidate[f"define_{def_num}_extreme_substituted"] = True
                    extreme_candidate[f"define_{def_num}_extreme_from_candle"] = def_candle_number
                    
                    # Update the definition_candles dictionary with the new location
                    definition_candles[def_num] = {
                        'candle': extreme_candidate,
                        'index': extreme_in_pattern_idx,
                        'candle_number': extreme_candle_number
                    }
                    
                    # Also update all_definition_candles
                    all_definition_candles[def_num] = definition_candles[def_num]
                    
        
        return patterns_dict
    
    def add_liquidity_sweepers_to_patterns(target_data_tf, new_key, original_candles):
        """
        Adds sweeper candle details to victim candles in patterns.
        Ensures victim candles have proper sweeper information and adds sweepers to the family.
        Sanitizes sweeper candles to only include essential fields.
        """
        if not isinstance(target_data_tf, dict):
            return

        pattern_key = f"{new_key}_patterns"
        patterns = target_data_tf.get(pattern_key, {})
        
        # Create a map of candle_number to candle for quick lookup from original candles
        # This contains the complete, marked-up candle data with sweeper information
        original_candle_map = {
            c.get("candle_number"): c 
            for c in original_candles 
            if isinstance(c, dict) and "candle_number" in c
        }

        # Define the allowed fields for sanitized sweeper candles
        allowed_sweeper_fields = {
            "open", "high", "low", "close", "volume", "spread", "real_volume",
            "symbol", "time", "candle_number", "timeframe",
            "candle_x", "candle_y", "candle_width", "candle_height",
            "candle_left", "candle_right", "candle_top", "candle_bottom",
            "swing_type", "is_swing", "active_color",
            "draw_x", "draw_y", "draw_w", "draw_h",
            "draw_left", "draw_right", "draw_top", "draw_bottom",
            "is_liquidity_sweep", "swept_victims", "swept_victim_number", "liquidity_price"
        }

        for p_name, family in patterns.items():
            if not isinstance(family, list):
                continue
                
            # Track victims we've already processed and sweepers we've added
            processed_victims = set()
            added_sweepers = set()
            
            # Create a new list to rebuild the family with updated victims and added sweepers
            new_family = []
            
            # First pass: Process all candles, updating victims with their sweeper info
            for candle in family:
                if not isinstance(candle, dict):
                    new_family.append(candle)
                    continue
                
                candle_num = candle.get("candle_number")
                if candle_num is None:
                    new_family.append(candle)
                    continue
                
                # Get the original candle data which has the liquidity sweep markings
                original_candle = original_candle_map.get(candle_num)
                
                if original_candle:
                    # Create a copy to avoid modifying the original
                    updated_candle = candle.copy()
                    
                    # Update the candle with liquidity sweep information from original
                    # This ensures victims have swept_by_liquidity, swept_by_candle_number, etc.
                    if original_candle.get("swept_by_liquidity"):
                        updated_candle["swept_by_liquidity"] = True
                        updated_candle["swept_by_candle_number"] = original_candle.get("swept_by_candle_number")
                        updated_candle["swept_by_candles"] = original_candle.get("swept_by_candles", [])
                        
                        # Mark as victim for processing
                        if candle_num not in processed_victims:
                            processed_victims.add(candle_num)
                    
                    # If this candle itself is a sweeper, update its sweeper info
                    if original_candle.get("is_liquidity_sweep"):
                        updated_candle["is_liquidity_sweep"] = True
                        updated_candle["swept_victims"] = original_candle.get("swept_victims", [])
                        updated_candle["swept_victim_number"] = original_candle.get("swept_victim_number")
                        updated_candle["liquidity_price"] = original_candle.get("liquidity_price")
                    
                    new_family.append(updated_candle)
                else:
                    # If no original data, keep as is
                    new_family.append(candle)
            
            # Second pass: Add missing sweeper candles that aren't already in the family
            for victim_num in processed_victims:
                # Find the victim in new_family to get its sweeper info
                victim_candle = None
                for candle in new_family:
                    if isinstance(candle, dict) and candle.get("candle_number") == victim_num:
                        victim_candle = candle
                        break
                
                if not victim_candle:
                    continue
                
                # Get sweeper candle number(s) from victim
                sweeper_nums = victim_candle.get("swept_by_candles", [])
                if not sweeper_nums:
                    # Try single sweeper number
                    sweeper_num = victim_candle.get("swept_by_candle_number")
                    if sweeper_num:
                        sweeper_nums = [sweeper_num]
                
                for sweeper_num in sweeper_nums:
                    # Check if sweeper is already in family
                    sweeper_exists = False
                    for candle in new_family:
                        if isinstance(candle, dict) and candle.get("candle_number") == sweeper_num:
                            sweeper_exists = True
                            break
                    
                    # If sweeper not in family and not already added, add it
                    if not sweeper_exists and sweeper_num not in added_sweepers:
                        # Find sweeper in original candles
                        original_sweeper = original_candle_map.get(sweeper_num)
                        if original_sweeper:
                            # Create sanitized sweeper copy
                            sweeper_copy = {}
                            for field in allowed_sweeper_fields:
                                if field in original_sweeper:
                                    sweeper_copy[field] = original_sweeper.get(field)
                            
                            # Ensure sweeper is properly marked
                            sweeper_copy["is_liquidity_sweep"] = True
                            sweeper_copy["swept_victim_number"] = victim_num
                            
                            # Add to new_family
                            new_family.append(sweeper_copy)
                            added_sweepers.add(sweeper_num)
            
            # Replace the old family with the new one
            if len(new_family) > len(family) or processed_victims:
                patterns[p_name] = new_family
        
        return target_data_tf
    
    def liquidity_flags_to_sweepers(target_data_tf, patterns_key, identify_config):
        """
        Adds define_{value}_liquidity: true flags to sweeper candles based on define candles they swept.
        
        This function should be called BEFORE draw_definition_tools to ensure sweepers have
        the liquidity flags properly set before drawing.
        
        Args:
            target_data_tf: The timeframe data dictionary containing patterns
            patterns_key: The key for the patterns in target_data_tf (e.g., "new_key_patterns")
            identify_config: Configuration containing define settings
        
        Returns:
            bool: True if any flags were added, False otherwise
        """
        if not identify_config or not target_data_tf:
            return False
        
        patterns = target_data_tf.get(patterns_key, {})
        flags_added = False
        
        #print(f"ADDING LIQUIDITY FLAGS TO SWEEPERS for {patterns_key}")
        
        for family_name, family in patterns.items():
            if not isinstance(family, list):
                continue
            
            # First, build maps of sweepers and their victims
            sweeper_by_number = {}  # {sweeper_candle_number: sweeper_candle}
            sweeper_for_victim = {}  # {victim_candle_number: sweeper_candle}
            
            # Pass 1: Identify all sweepers and map them to their victims
            for candle in family:
                if not isinstance(candle, dict):
                    continue
                
                candle_num = candle.get("candle_number")
                if candle_num is None:
                    continue
                
                # If this candle is a sweeper
                if candle.get("is_liquidity_sweep") is True:
                    sweeper_by_number[candle_num] = candle
                    
                    # Map this sweeper to all its victims
                    swept_victims = candle.get("swept_victims", [])
                    if swept_victims:
                        for victim_num in swept_victims:
                            sweeper_for_victim[victim_num] = candle
                    
                    # Handle single victim case
                    single_victim = candle.get("swept_victim_number")
                    if single_victim and single_victim not in sweeper_for_victim:
                        sweeper_for_victim[single_victim] = candle
            
            # Pass 2: Find all define candles and add flags to their sweepers
            for candle in family:
                if not isinstance(candle, dict):
                    continue
                
                # Check if this candle is a define (any define_n)
                define_name = None
                for key in candle.keys():
                    if key.startswith("define_") and candle[key] is True:
                        define_name = key
                        break
                
                if not define_name:
                    continue
                
                candle_num = candle.get("candle_number")
                if candle_num is None:
                    continue
                
                # Check account management to see if this define should be processed
                define_settings = identify_config.get(define_name, {})
                if define_settings:
                    drawing_enabled = define_settings.get("enable_drawing", True)
                    if not drawing_enabled:
                        # Skip if drawing is disabled for this define
                        continue
                
                # Find the sweeper for this define candle
                sweeper = None
                
                # Priority 1: Check victim mapping
                if candle_num in sweeper_for_victim:
                    sweeper = sweeper_for_victim[candle_num]
                
                # Priority 2: Check direct swept_by_candle_number
                if not sweeper:
                    swept_by_num = candle.get("swept_by_candle_number")
                    if swept_by_num and swept_by_num in sweeper_by_number:
                        sweeper = sweeper_by_number[swept_by_num]
                
                # If we found a sweeper, add the liquidity flag
                if sweeper:
                    liquidity_flag = f"{define_name}_liquidity"
                    
                    # Check if flag already exists to avoid duplicates
                    if not sweeper.get(liquidity_flag):
                        sweeper[liquidity_flag] = True
                        flags_added = True
                        #print(f"  🏷️ Added '{liquidity_flag}: true' to sweeper candle #{sweeper.get('candle_number')} for define #{candle_num}")
        
        return flags_added

    def intruder_and_outlaw_check(processed_data):
        for file_key, candles in processed_data.items():
            if not isinstance(candles, list):
                continue

            for i, candle in enumerate(candles):
                if not isinstance(candle, dict):
                    continue

                sender_num = candle.get("candle_number", i)
                sender_swing = candle.get("swing_type", "").lower()

                # 1. Identify connection keys from identify_definitions
                # Format: define_2_firstfound_129_in_connection_with_define_1_68
                connection_keys = [k for k in candle.keys() if "_in_connection_with_" in k]
                
                for conn_key in connection_keys:
                    try:
                        # Parse the logic label (identical/opposite) stored as the value in identify_definitions
                        logic_label = candle[conn_key] 
                        
                        # Split key to find the messenger number (last part of the string)
                        parts = conn_key.split('_')
                        messenger_num = int(parts[-1])
                        
                        # 2. INTRUDER CHECK (Liquidity Sweep)
                        messenger_candle = next((c for c in candles if isinstance(c, dict) and c.get("candle_number") == messenger_num), None)
                        
                        if messenger_candle and messenger_candle.get("swept_by_liquidity") is True:
                            intruder_num = messenger_candle.get("swept_by_candle_number")
                            if intruder_num is not None and messenger_num < intruder_num < sender_num:
                                # Construct dynamic key for Intruder
                                intruder_key = f"{conn_key}_{logic_label}_condition_beyond_firstchecked_intruder_number_{intruder_num}"
                                candle[intruder_key] = True

                        # 3. OUTLAW CHECK (Opposite Swing in Range)
                        outlaw_found = None
                        for mid_candle in candles:
                            if not isinstance(mid_candle, dict): continue
                            mid_num = mid_candle.get("candle_number")
                            
                            # Only check candles between the 'firstchecked' (messenger) and current 'sender'
                            if mid_num is not None and messenger_num < mid_num < sender_num:
                                mid_swing = mid_candle.get("swing_type", "").lower()
                                
                                is_outlaw = False
                                if sender_swing == "swing_low" and mid_swing == "swing_high":
                                    is_outlaw = True
                                elif sender_swing == "swing_high" and mid_swing == "swing_low":
                                    is_outlaw = True
                                
                                if is_outlaw:
                                    # Capture the first occurrence
                                    if outlaw_found is None or mid_num < outlaw_found:
                                        outlaw_found = mid_num

                        if outlaw_found is not None:
                            # Construct dynamic key for Outlaw
                            # Example: define_2_firstfound_129_in_connection_with_define_1_68_opposite_condition_beyond_firstchecked_identity_outlaw_number_130
                            outlaw_key = f"{conn_key}_{logic_label}_condition_beyond_firstchecked_identity_outlaw_number_{outlaw_found}"
                            candle[outlaw_key] = True

                    except (ValueError, IndexError):
                        continue

        return processed_data

    def identify_poi(target_data_tf, new_key, original_candles, poi_config):
        """
        Identifies Point of Interest (Breaker) based strictly on price violation.
        Now uses open price comparison between from_subject and after_subject candles
        to determine hit direction, regardless of swing type.
        Tags anchor candles with 'from': True and 'after': True.
        Hit direction determined by: if after_subject open > from_subject open -> hit_from_above,
        if after_subject open < from_subject open -> hit_from_below.
        """
        if not poi_config or not isinstance(target_data_tf, dict):
            return

        pattern_key = f"{new_key}_patterns"
        patterns = target_data_tf.get(pattern_key, {})
        
        from_sub = poi_config.get("from_subject")  
        after_sub = poi_config.get("after_subject") 
        
        # Only check for the exact values, don't auto-append _liquidity
        from_variants = [from_sub] if from_sub else []
        after_variants = [after_sub] if after_sub else []

        candle_map = {
            c.get("candle_number"): c 
            for c in original_candles 
            if isinstance(c, dict) and "candle_number" in c
        }

        for p_name, family in patterns.items():
            # 1. Locate the anchor candles - check only the exact values
            from_candle = None
            for variant in from_variants:
                from_candle = next((c for c in family if c.get(variant) is True), None)
                if from_candle:
                    break
            
            after_candle = None
            for variant in after_variants:
                after_candle = next((c for c in family if c.get(variant) is True), None)
                if after_candle:
                    break
            
            if not from_candle or not after_candle:
                continue

            # Tag anchor candles
            from_candle["from"] = True
            after_candle["after"] = True
                    
            after_num = after_candle.get("candle_number")
            
            # Calculate center price and center coordinates for from_candle
            from_high = from_candle.get("high")
            from_low = from_candle.get("low")
            center_price = None
            if from_high is not None and from_low is not None:
                center_price = (from_high + from_low) / 2
                from_candle["center_price"] = center_price
            
            # Calculate center coordinates (pixel position)
            from_top = from_candle.get("candle_top")
            from_bottom = from_candle.get("candle_bottom")
            from_left = from_candle.get("candle_left")
            from_right = from_candle.get("candle_right")
            from_x = from_candle.get("candle_x")
            from_y = from_candle.get("candle_y")
            from_height = from_candle.get("candle_height")
            from_width = from_candle.get("candle_width")
            
            center_coord_y = None
            if from_top is not None and from_bottom is not None:
                center_coord_y = (from_top + from_bottom) / 2
                from_candle["center_coord_y"] = center_coord_y
            elif from_y is not None and from_height is not None:
                center_coord_y = from_y + (from_height / 2)
                from_candle["center_coord_y"] = center_coord_y
            
            center_coord_x = None
            if from_left is not None and from_right is not None:
                center_coord_x = (from_left + from_right) / 2
                from_candle["center_coord_x"] = center_coord_x
            elif from_x is not None and from_width is not None:
                center_coord_x = from_x + (from_width / 2)
                from_candle["center_coord_x"] = center_coord_x
            
            # Determine target price level from from_candle
            # Check which price key to use from config
            swing_type = from_candle.get("swing_type", "").lower()
            
            if "high" in swing_type:
                price_key = poi_config.get("subject_is_swinghigh_or_lowerhigh", "low")
            else:
                price_key = poi_config.get("subject_is_swinglow_or_higherlow", "high")
            
            # Check if center_price is requested
            if price_key == "center_price":
                target_price = from_candle.get("center_price")
            else:
                clean_key = price_key.replace("_price", "") 
                target_price = from_candle.get(clean_key)
            
            if target_price is None:
                continue

            # Determine hit direction based on open price comparison
            from_open = from_candle.get("open")
            after_open = after_candle.get("open")
            
            # Default values
            hit_from_above = False
            hit_from_below = False
            
            if from_open is not None and after_open is not None:
                if after_open > from_open:
                    # After subject open is above from subject open -> price came from above to hit below
                    hit_from_above = True
                elif after_open < from_open:
                    # After subject open is below from subject open -> price came from below to hit above
                    hit_from_below = True
                # If equal, both remain False (neutral/direct hit)

            hitler_record = None

            # Search for the violator candle after 'after_subject'
            for oc in original_candles:
                if not isinstance(oc, dict) or oc.get("candle_number") <= after_num:
                    continue
                    
                # Check for price violation based on swing type
                if swing_type == "swing_low":
                    violator_low = oc.get("low")
                    if violator_low is not None and violator_low < target_price:
                        hitler_record = oc.copy()
                        break
                
                elif swing_type == "swing_high":
                    violator_high = oc.get("high")
                    if violator_high is not None and violator_high > target_price:
                        hitler_record = oc.copy()
                        break
                
                else:
                    continue

            if hitler_record:
                h_num = hitler_record.get("candle_number")
                direction_label = "below" if swing_type == "swing_low" else "above"
                
                # Attach direction flags to hitler candle (determined by open price comparison)
                hitler_record["hit_from_above"] = hit_from_above
                hitler_record["hit_from_below"] = hit_from_below
                
                label = f"after_subject_{after_sub}_violator_{h_num}_breaks_{direction_label}_{from_sub}_{price_key}_price_{target_price:.5f}"
                
                from_candle[label] = True
                hitler_record["is_hitler_poi"] = True
                hitler_record["point_of_interest"] = True
                
                # Enrich coordinates for visualization
                coordinate_keys = [
                    "candle_x", "candle_y", "candle_width", "candle_height",
                    "candle_left", "candle_right", "candle_top", "candle_bottom"
                ]
                full_record = candle_map.get(h_num)
                if full_record:
                    for k in coordinate_keys:
                        hitler_record[k] = full_record.get(k)
                
                family.append(hitler_record)
                from_candle["pattern_entry"] = True
            else:
                from_candle["pattern_entry"] = True

        return target_data_tf

    def identify_poi_mitigation(target_data_tf, new_key, poi_config):
        """
        Removes patterns where specific candles (restrict_definitions_mitigation) 
        violate the target price based on open price comparison between from_subject and restrict candles.
        Now uses universal method: if restrict candle open > from candle open -> hit_from_above,
        if restrict candle open < from candle open -> hit_from_below.
        No longer relies on swing type for direction assumptions.
        Supports center_price as target price level.
        """
        if not poi_config or not isinstance(target_data_tf, dict):
            return

        pattern_key = f"{new_key}_patterns"
        patterns = target_data_tf.get(pattern_key, {})
        from_sub = poi_config.get("from_subject")
        restrict_raw = poi_config.get("restrict_definitions_mitigation")
        
        if not restrict_raw:
            return

        restrict_subs = [s.strip() for s in restrict_raw.split(",")]
        
        # Only check for the exact from_subject value, don't auto-append _liquidity
        from_variants = [from_sub] if from_sub else []
        
        patterns_to_remove = []

        for p_name, family in patterns.items():
            # Find from_candle using exact value only
            from_candle = None
            for variant in from_variants:
                from_candle = next((c for c in family if c.get(variant) is True), None)
                if from_candle:
                    break
                    
            if not from_candle:
                continue

            # Calculate center_price if not already present
            if "center_price" not in from_candle:
                from_high = from_candle.get("high")
                from_low = from_candle.get("low")
                if from_high is not None and from_low is not None:
                    from_candle["center_price"] = (from_high + from_low) / 2

            target_swingtype = from_candle.get("swing_type", "").lower()
            
            # Determine the target price from configuration
            if "high" in target_swingtype:
                price_key = poi_config.get("subject_is_swinghigh_or_lowerhigh", "low")
            else:
                price_key = poi_config.get("subject_is_swinglow_or_higherlow", "high")

            # Check if center_price is requested
            if price_key == "center_price":
                target_price = from_candle.get("center_price")
            else:
                clean_key = price_key.replace("_price", "") 
                target_price = from_candle.get(clean_key)
            
            if target_price is None:
                continue
            
            # Get from_candle open price for comparison
            from_open = from_candle.get("open")

            is_mitigated = False
            
            # Check each restrict subject using exact values only (no auto-appended _liquidity)
            for sub_key in restrict_subs:
                # Only check for the exact subject value
                sub_variants = [sub_key]
                
                restrict_candle = None
                for variant in sub_variants:
                    restrict_candle = next((c for c in family if c.get(variant) is True), None)
                    if restrict_candle:
                        break
                
                if restrict_candle:
                    # Get restrict_candle open price for direction determination
                    restrict_open = restrict_candle.get("open")
                    
                    # Determine hit direction based on open price comparison
                    hit_from_above = False
                    hit_from_below = False
                    
                    if from_open is not None and restrict_open is not None:
                        if restrict_open > from_open:
                            hit_from_above = True
                        elif restrict_open < from_open:
                            hit_from_below = True
                    
                    # Check for price violation based on swing type
                    if target_swingtype == "swing_low":
                        violator_low = restrict_candle.get("low")
                        # If violator_low is < target_price, it's a mitigation
                        if violator_low is not None and violator_low < target_price:
                            # Attach direction flags to restrict candle
                            restrict_candle["hit_from_above"] = hit_from_above
                            restrict_candle["hit_from_below"] = hit_from_below
                            restrict_candle["is_mitigation"] = True
                            is_mitigated = True
                            break
                    
                    elif target_swingtype == "swing_high":
                        violator_high = restrict_candle.get("high")
                        # If violator_high is > target_price, it's a mitigation
                        if violator_high is not None and violator_high > target_price:
                            # Attach direction flags to restrict candle
                            restrict_candle["hit_from_above"] = hit_from_above
                            restrict_candle["hit_from_below"] = hit_from_below
                            restrict_candle["is_mitigation"] = True
                            is_mitigated = True
                            break
                    
                    else:
                        # ("no violator")
                        continue

            if is_mitigated:
                patterns_to_remove.append(p_name)

        # Clean up patterns that hit the mitigation criteria
        for p_name in patterns_to_remove:
            del patterns[p_name]

        return target_data_tf

    def identify_candle_after_poi_and_apply_condition(target_data_tf, new_key, original_candles, poi_config, identify_config):
        """
        Validates that the candle(s) after the POI hit meets a condition relative to the entry level.
        Supports three selection types:
        - fixed: Check a specific candle position (N) - must meet condition
        - random: Check N candles after POI, at least one must meet condition
        - sequence: Check N candles after POI, ALL must meet condition
        Adds candle_after_poi flag to the found candle(s) in the pattern family.
        If condition is not met and remove_outlaw is True, the entire pattern record is removed.
        If remove_outlaw is False, patterns that don't meet the condition are kept but not flagged.
        Now includes hit direction tracking to determine if candle is above or below entry.
        """
        if not poi_config or not original_candles:
            return
        
        pattern_key = f"{new_key}_patterns"
        patterns = target_data_tf.get(pattern_key, {})
        
        # Get configuration
        candles_after_config = poi_config.get("candles_after_poi_confirmation", {})
        if not candles_after_config:
            return
        
        selection_type = candles_after_config.get("selection_type", "fixed").lower()
        candle_position = candles_after_config.get("candle_position", 1)  # For fixed: position; For random/sequence: count
        condition_mode = candles_after_config.get("candle_condition", "").lower()  # "behind_entry" or "beyond_entry"
        remove_outlaw = candles_after_config.get("remove_outlaw", False)  # Default to False if not specified
        
        if not condition_mode:
            return
        
        from_sub = poi_config.get("from_subject")
        from_variants = [from_sub] if from_sub else []
        
        # Build candle map for quick lookup
        candle_map = {c.get("candle_number"): c for c in original_candles if isinstance(c, dict) and "candle_number" in c}
        
        # Track patterns to delete (those that don't meet condition) - only if remove_outlaw is True
        patterns_to_delete = []
        
        for p_name, family in list(patterns.items()):
            # Find the entry level candle (from_subject)
            entry_candle = None
            for variant in from_variants:
                entry_candle = next((c for c in family if c.get(variant) is True), None)
                if entry_candle:
                    break
            
            if not entry_candle:
                if remove_outlaw:
                    patterns_to_delete.append(p_name)
                continue
            
            # Find the POI hitler candle in the family
            hitler_candle = next((c for c in family if c.get("is_hitler_poi") is True), None)
            
            if not hitler_candle:
                if remove_outlaw:
                    patterns_to_delete.append(p_name)
                continue
            
            # Get hit direction from the hitler candle
            hit_from_above = hitler_candle.get("hit_from_above", False)
            hit_from_below = hitler_candle.get("hit_from_below", False)
            
            # Get the hitler candle number
            hitler_num = hitler_candle.get("candle_number")
            if hitler_num is None:
                if remove_outlaw:
                    patterns_to_delete.append(p_name)
                continue
            
            # Get entry level prices and swing type
            entry_type = entry_candle.get("swing_type", "").lower()
            
            # Determine which price to use from entry level based on config
            if "high" in entry_type:
                price_key = poi_config.get("subject_is_swinghigh_or_lowerhigh", "low")
            else:
                price_key = poi_config.get("subject_is_swinglow_or_higherlow", "high")
            
            clean_key = price_key.replace("_price", "")
            entry_price = entry_candle.get(clean_key)
            
            if entry_price is None:
                if remove_outlaw:
                    patterns_to_delete.append(p_name)
                continue
            
            # Determine which candles to check based on selection type
            candles_to_check = []
            
            if selection_type == "fixed":
                # Check only the specific candle position
                target_candle_num = hitler_num + candle_position
                target_candle = candle_map.get(target_candle_num)
                if target_candle:
                    candles_to_check = [(target_candle_num, target_candle)]
            
            elif selection_type == "random":
                # Check all candles from position 1 to N
                for pos in range(1, candle_position + 1):
                    target_candle_num = hitler_num + pos
                    target_candle = candle_map.get(target_candle_num)
                    if target_candle:
                        candles_to_check.append((target_candle_num, target_candle))
            
            elif selection_type == "sequence":
                # Check all candles from position 1 to N (must all meet condition)
                for pos in range(1, candle_position + 1):
                    target_candle_num = hitler_num + pos
                    target_candle = candle_map.get(target_candle_num)
                    if target_candle:
                        candles_to_check.append((target_candle_num, target_candle))
                    else:
                        # Missing candle breaks the sequence
                        candles_to_check = []
                        break
            
            else:
                # Default to fixed behavior
                selection_type = "fixed"
                target_candle_num = hitler_num + candle_position
                target_candle = candle_map.get(target_candle_num)
                if target_candle:
                    candles_to_check = [(target_candle_num, target_candle)]
            
            if not candles_to_check:
                if remove_outlaw:
                    patterns_to_delete.append(p_name)
                continue
            
            # Function to check if a candle meets the condition
            def check_condition(target_candle, target_candle_num, entry_price, entry_type, condition_mode):
                target_high = target_candle.get("high")
                target_low = target_candle.get("low")
                
                if target_high is None or target_low is None:
                    return False, None, None
                
                # Determine if candle after POI is above or below entry level
                candle_above_entry = False
                candle_below_entry = False
                
                # Check if the entire candle is above the entry level
                if target_low > entry_price:
                    candle_above_entry = True
                # Check if the entire candle is below the entry level
                elif target_high < entry_price:
                    candle_below_entry = True
                # If candle straddles the entry level, check where most of the candle is relative to entry
                else:
                    # Calculate midpoint of candle to determine bias
                    candle_mid = (target_high + target_low) / 2
                    if candle_mid > entry_price:
                        candle_above_entry = True
                    else:
                        candle_below_entry = True
                
                # Apply the condition logic
                condition_met = False
                mode = "behind" if "behind" in condition_mode else "beyond"
                
                if mode == "behind":
                    if "high" in entry_type:  # Entry is swing_high
                        condition_met = (target_low > entry_price) or (target_high < entry_price)
                    elif "low" in entry_type:  # Entry is swing_low
                        condition_met = (target_high < entry_price) or (target_low > entry_price)
                
                elif mode == "beyond":
                    if "high" in entry_type:  # Entry is swing_high
                        condition_met = (target_high > entry_price) or (target_low < entry_price)
                    elif "low" in entry_type:  # Entry is swing_low
                        condition_met = (target_low < entry_price) or (target_high > entry_price)
                
                return condition_met, candle_above_entry, candle_below_entry
            
            # Check candles based on selection type
            condition_met_overall = False
            candles_to_add = []
            
            if selection_type == "fixed":
                # Single candle must meet condition
                target_candle_num, target_candle = candles_to_check[0]
                condition_met, candle_above_entry, candle_below_entry = check_condition(
                    target_candle, target_candle_num, entry_price, entry_type, condition_mode
                )
                
                if condition_met:
                    condition_met_overall = True
                    candles_to_add.append((target_candle_num, target_candle, candle_above_entry, candle_below_entry))
            
            elif selection_type == "random":
                # At least one candle must meet condition
                for target_candle_num, target_candle in candles_to_check:
                    condition_met, candle_above_entry, candle_below_entry = check_condition(
                        target_candle, target_candle_num, entry_price, entry_type, condition_mode
                    )
                    
                    if condition_met:
                        condition_met_overall = True
                        candles_to_add.append((target_candle_num, target_candle, candle_above_entry, candle_below_entry))
                        break  # Found one, stop checking
            
            elif selection_type == "sequence":
                # ALL candles must meet condition
                all_met = True
                temp_candles_to_add = []
                
                for target_candle_num, target_candle in candles_to_check:
                    condition_met, candle_above_entry, candle_below_entry = check_condition(
                        target_candle, target_candle_num, entry_price, entry_type, condition_mode
                    )
                    
                    if condition_met:
                        temp_candles_to_add.append((target_candle_num, target_candle, candle_above_entry, candle_below_entry))
                    else:
                        all_met = False
                        break
                
                if all_met and temp_candles_to_add:
                    condition_met_overall = True
                    candles_to_add = temp_candles_to_add
            
            # If condition is NOT met and remove_outlaw is True, mark pattern for deletion
            if not condition_met_overall:
                if remove_outlaw:
                    patterns_to_delete.append(p_name)
                continue
            
            # If condition is met, add the candle(s) to the family with flags
            for target_candle_num, target_candle, candle_above_entry, candle_below_entry in candles_to_add:
                # Create a copy to avoid modifying original
                candle_copy = target_candle.copy()
                candle_copy["candle_after_poi"] = True
                candle_copy[f"candle_after_poi_position_{target_candle_num - hitler_num}"] = True
                candle_copy[f"candle_after_poi_condition_{condition_mode}"] = True
                candle_copy[f"candle_after_poi_selection_type_{selection_type}"] = True
                
                # Add hit direction and position relative to entry level
                if hit_from_above:
                    candle_copy["hit_from_above_poi"] = True
                    if candle_above_entry:
                        candle_copy["candle_after_poi_above_entry"] = True
                    elif candle_below_entry:
                        candle_copy["candle_after_poi_below_entry"] = True
                
                elif hit_from_below:
                    candle_copy["hit_from_below_poi"] = True
                    if candle_above_entry:
                        candle_copy["candle_after_poi_above_entry"] = True
                    elif candle_below_entry:
                        candle_copy["candle_after_poi_below_entry"] = True
                
                else:
                    # Neutral hit (direct hit without clear direction)
                    candle_copy["hit_from_neutral_poi"] = True
                    if candle_above_entry:
                        candle_copy["candle_after_poi_above_entry"] = True
                    elif candle_below_entry:
                        candle_copy["candle_after_poi_below_entry"] = True
                
                # Also mark whether the candle after POI continued in the same direction as the hit
                if hit_from_above and candle_below_entry:
                    candle_copy["continued_direction_after_poi"] = True
                    candle_copy["poi_continued_downward"] = True
                elif hit_from_below and candle_above_entry:
                    candle_copy["continued_direction_after_poi"] = True
                    candle_copy["poi_continued_upward"] = True
                
                # Add to family
                family.append(candle_copy)
            
            # Also mark on entry candle that condition was met with hit direction context
            entry_candle[f"candle_after_poi_condition_met_{candle_position}_{condition_mode}_{selection_type}"] = True
            entry_candle[f"candle_after_poi_hit_direction_{'above' if hit_from_above else 'below' if hit_from_below else 'neutral'}"] = True
            
            # Mark the selection type and count on entry candle
            entry_candle[f"candle_after_poi_selection_type_{selection_type}_count_{candle_position}"] = True
            entry_candle[f"candle_after_poi_candles_checked_{len(candles_to_check)}"] = True
            
            # Mark above/below based on the first candle found
            first_candle_above = candles_to_add[0][2] if candles_to_add else False
            first_candle_below = candles_to_add[0][3] if candles_to_add else False
            
            if first_candle_above:
                entry_candle[f"candle_after_poi_above_entry_{candle_position}"] = True
            elif first_candle_below:
                entry_candle[f"candle_after_poi_below_entry_{candle_position}"] = True
        
        # Remove patterns that didn't meet the condition (only if remove_outlaw is True)
        if remove_outlaw:
            for p_name in patterns_to_delete:
                if p_name in patterns:
                    del patterns[p_name]

    def remove_outlawed_swings_in_between_definitions(target_data_tf, new_key, original_candles, poi_config):
        """
        Removes patterns that have ANY swing type between the specific define_1 and define_2
        candles found in the pattern family.
        
        This function finds the define_1 candle (with 'from': True) and define_2 candle 
        (with 'after': True) in the pattern, then checks the FULL original candle data
        for any swings between their candle numbers.
        
        Config format:
            "remove_outlawed_swings_in_between_definitions": "define_1_define_2, define_2_define_3"
        
        Args:
            target_data_tf: The timeframe data containing patterns
            new_key: The key for the current pattern
            original_candles: The full original candle data
            poi_config: The POI configuration containing the setting
        
        Returns:
            target_data_tf: The modified timeframe data with outlaw patterns removed
        """
        if not poi_config or not isinstance(target_data_tf, dict) or not original_candles:
            return target_data_tf

        # Get the configuration
        remove_config = poi_config.get("remove_outlawed_swings_in_between_definitions", "")
        if not remove_config:
            return target_data_tf

        pattern_key = f"{new_key}_patterns"
        patterns = target_data_tf.get(pattern_key, {})
        if not patterns:
            return target_data_tf

        # Parse the configuration
        pairs = [p.strip() for p in remove_config.split(",") if p.strip()]
        if not pairs:
            return target_data_tf

        # Build a lookup dictionary of original candles by candle_number
        original_candle_lookup = {}
        for candle in original_candles:
            if isinstance(candle, dict) and candle.get("candle_number") is not None:
                original_candle_lookup[candle["candle_number"]] = candle

        # Track patterns to remove
        patterns_to_remove = []

        # Process each pattern family
        for p_name, family in patterns.items():
            if not isinstance(family, list):
                continue

            # Check each pair configuration
            for pair in pairs:
                parts = pair.split("_")
                if len(parts) < 4:
                    continue
                    
                def1_key = f"{parts[0]}_{parts[1]}"  # e.g., "define_1"
                def2_key = f"{parts[2]}_{parts[3]}"  # e.g., "define_2"

                # Find the define_1 candle (with 'from': True) and define_2 candle (with 'after': True)
                from_candle = None  # This is the define_1 candle
                after_candle = None  # This is the define_2 candle
                
                for candle in family:
                    if isinstance(candle, dict):
                        # The define_1 candle has 'from': True
                        if candle.get("from") is True and candle.get(def1_key) is True:
                            from_candle = candle
                        # The define_2 candle has 'after': True
                        if candle.get("after") is True and candle.get(def2_key) is True:
                            after_candle = candle

                # If we can't find both, skip this pattern
                if not from_candle or not after_candle:
                    continue

                # Get candle numbers
                from_num = from_candle.get("candle_number")
                after_num = after_candle.get("candle_number")
                
                if from_num is None or after_num is None:
                    continue

                # Determine the range between the two definitions
                start = min(from_num, after_num) + 1
                end = max(from_num, after_num) - 1

                # If there are no candles between them, skip
                if start > end:
                    continue

                # Check if there are ANY swing candles between them in the FULL original data
                has_swing_between = False
                
                for candle_num in range(start, end + 1):
                    original_candle = original_candle_lookup.get(candle_num)
                    if not original_candle:
                        continue
                    
                    # Check if this candle has a swing_type (meaning it's a swing candle)
                    swing_type = original_candle.get("swing_type", "").lower()
                    if swing_type and swing_type in ["swing_high", "swing_low"]:
                        has_swing_between = True
                        break

                # If ANY swing exists between the definitions, mark this pattern for removal
                if has_swing_between:
                    patterns_to_remove.append(p_name)
                    break  # No need to check other pairs for this pattern

        # Remove all marked patterns
        for p_name in patterns_to_remove:
            if p_name in patterns:
                del patterns[p_name]
                

        return target_data_tf

    def draw_poi_tools(img, target_data_tf, new_key, poi_config):
        """
        Draws visual markers on the image. 
        Boxes feature a single-edge border on the 'sensitive' price level.
        Updates 'from_candle' with flags regarding its extension or break status.
        Now attaches the formatted time of the breaker candle to the center of boxes.
        Now respects the exact from_subject value without auto-appending _liquidity.
        Skips drawing duplicate POIs that stop at the same Hitler candle.
        Skips drawing duplicate POIs that start from the same from_candle.
        Deletes skipped patterns entirely from the data structure.
        Handles center_price by drawing a horizontal line from the candle's center instead of a box.
        """
        if not poi_config or img is None:
            return img

        pattern_key = f"{new_key}_patterns"
        patterns = target_data_tf.get(pattern_key, {})
        
        drawing_tool = poi_config.get("drawing_tool", "horizontal_line")
        from_sub = poi_config.get("from_subject")
        
        # FIX: Only check for the exact value provided, don't auto-append _liquidity
        from_variants = [from_sub] if from_sub else []
        
        # Config mapping for sensitive edge
        hh_lh_edge = poi_config.get("subject_is_swinghigh_or_lowerhigh") # e.g., "low_price", "center_price"
        ll_hl_edge = poi_config.get("subject_is_swinglow_or_higherlow")   # e.g., "high_price", "center_price"
        
        # Check if we should use center_price behavior for this pattern
        use_center_price = (hh_lh_edge == "center_price" or ll_hl_edge == "center_price")
        
        # Override drawing tool if center_price is specified
        if use_center_price:
            drawing_tool = "horizontal_line"  # Force horizontal line instead of box
        
        img_height, img_width = img.shape[:2]
        
        # Track which Hitler candles have already been drawn
        drawn_hitler_candles = set()
        # Track which from_candles have already been processed
        drawn_from_candles = set()
        
        # Create a list to store pattern names that should be deleted
        patterns_to_delete = []

        for p_name, family in patterns.items():
            # 1. Identify the origin (from_candle) using exact value only
            from_candle = None
            from_candle_key = None
            
            for variant in from_variants:
                from_candle = next((c for c in family if c.get(variant) is True), None)
                if from_candle:
                    # Create a unique key for this from_candle using its candle number
                    from_candle_num = from_candle.get("candle_number", "unknown")
                    from_candle_key = f"from_{from_candle_num}"
                    break
                    
            if not from_candle:
                # If no from_candle found, delete this pattern
                patterns_to_delete.append(p_name)
                continue
            
            # Check if we've already drawn from this from_candle
            if from_candle_key in drawn_from_candles:
                # Mark as duplicate and delete this pattern
                from_candle["skipped_duplicate_from_candle"] = True
                patterns_to_delete.append(p_name)
                continue
            
            # Mark this from_candle as drawn
            drawn_from_candles.add(from_candle_key)

            # Locate the breaker candle using the boolean flags
            breaker_candle = next((c for c in family if c.get("is_hitler_poi") or c.get("is_invalid_hitler") or c.get("point_of_interest")), None)
            
            # If there's a breaker candle, check if we've already drawn a POI for this Hitler candle
            if breaker_candle:
                hitler_num = breaker_candle.get("candle_number", "unknown")
                
                # Create a unique key for this Hitler candle
                hitler_key = f"hitler_{hitler_num}"
                
                # If we've already drawn a POI for this Hitler candle, delete this pattern
                if hitler_key in drawn_hitler_candles:
                    # Mark as duplicate to avoid processing
                    from_candle["skipped_duplicate_poi"] = True
                    patterns_to_delete.append(p_name)
                    continue
                
                # Mark this Hitler candle as drawn
                drawn_hitler_candles.add(hitler_key)
            
            # 2. Determine X boundaries and Update Flags
            start_x = int(from_candle.get("draw_right", from_candle.get("candle_right", 0)))
            
            formatted_date = ""
            if breaker_candle:
                end_x = int(breaker_candle.get("draw_left", breaker_candle.get("candle_left", img_width)))
                color = (0, 0, 255)  # Red for broken
                
                # FIX: Get the candle_number from the breaker record to avoid "unknown"
                hitler_num = breaker_candle.get("candle_number", "unknown")
                
                # Update the status flags on the origin candle
                from_candle[f"drawn_and_stopped_on_hitler{hitler_num}"] = True
                
                # --- DATE FORMATTING LOGIC ---
                raw_time = breaker_candle.get("time", "")
                try:
                    # Convert "2026-02-13 19:00:00" -> "Feb 13, 2026"
                    dt_obj = datetime.strptime(raw_time, "%Y-%m-%d %H:%M:%S")
                    formatted_date = dt_obj.strftime("%b %d, %Y")
                except (ValueError, TypeError):
                    formatted_date = ""

            else:
                end_x = img_width
                color = (0, 255, 0)  # Green for active
                from_candle["pending_entry_level"] = True

            # 3. Handle Drawing Tools
            
            # --- SPECIAL CASE: CENTER_PRICE with HORIZONTAL LINE ---
            if use_center_price:
                # Calculate the center Y coordinate from the candle's high and low
                candle_high = int(from_candle.get("draw_top", from_candle.get("high_price", 0)))
                candle_low = int(from_candle.get("draw_bottom", from_candle.get("low_price", 0)))
                center_y = (candle_high + candle_low) // 2
                
                # Draw dashed or solid horizontal line from center
                if "dashed" in drawing_tool:
                    dash_length, gap_length = 10, 5
                    curr_x = start_x
                    while curr_x < end_x:
                        next_x = min(curr_x + dash_length, end_x)
                        cv2.line(img, (curr_x, center_y), (next_x, center_y), color, 2)
                        curr_x += dash_length + gap_length
                else:
                    # Standard horizontal line from center
                    cv2.line(img, (start_x, center_y), (end_x, center_y), color, 2)
                
                # Add date text if available (positioned near the line)
                if formatted_date:
                    font = cv2.FONT_HERSHEY_SIMPLEX
                    font_scale = 0.4
                    thickness = 1
                    text_size = cv2.getTextSize(formatted_date, font, font_scale, thickness)[0]
                    
                    # Position text above the line if space allows, otherwise below
                    text_x = start_x + 5  # Slight offset from left edge
                    if center_y - 10 > text_size[1]:
                        text_y = center_y - 5
                    else:
                        text_y = center_y + text_size[1] + 5
                    
                    cv2.putText(img, formatted_date, (text_x, text_y), font, font_scale, (0, 0, 0), thickness, cv2.LINE_AA)
            
            # --- TOOL: BOX (only if not overridden by center_price) ---
            elif "box" in drawing_tool:
                y_high = int(from_candle.get("draw_top", 0))
                y_low = int(from_candle.get("draw_bottom", 0))
                
                # Draw Transparent Fill
                black_color = (0, 0, 0) 
                overlay = img.copy()
                cv2.rectangle(overlay, (start_x, y_high), (end_x, y_low), black_color, -1)
                cv2.addWeighted(overlay, 0.15, img, 0.85, 0, img)

                # --- TEXT DRAWING (Box Center) ---
                if formatted_date:
                    font = cv2.FONT_HERSHEY_SIMPLEX
                    font_scale = 0.4
                    thickness = 1
                    # Calculate text size to offset for true centering
                    text_size = cv2.getTextSize(formatted_date, font, font_scale, thickness)[0]
                    
                    text_x = start_x + (end_x - start_x) // 2 - text_size[0] // 2
                    text_y = y_high + (y_low - y_high) // 2 + text_size[1] // 2
                    
                    cv2.putText(img, formatted_date, (text_x, text_y), font, font_scale, black_color, thickness, cv2.LINE_AA)

                # Determine Sensitive Border logic
                swing_type = from_candle.get("swing_type", "").lower()
                border_y = None

                if "swing_high" in swing_type or "lower_high" in swing_type:
                    border_y = y_low if hh_lh_edge == "low_price" else y_high
                elif "swing_low" in swing_type or "higher_low" in swing_type:
                    border_y = y_high if ll_hl_edge == "high_price" else y_low

                # Draw the single sensitive border line
                if border_y is not None:
                    cv2.line(img, (start_x, border_y), (end_x, border_y), black_color, 1)

            # --- TOOL: DASHED HORIZONTAL LINE ---
            elif "dashed_horizontal_line" in drawing_tool:
                swing_type = from_candle.get("swing_type", "").lower()
                if "high" in swing_type:
                    target_y = int(from_candle.get("draw_top", 0))
                else:
                    target_y = int(from_candle.get("draw_bottom", 0))

                dash_length, gap_length = 10, 5
                curr_x = start_x
                while curr_x < end_x:
                    next_x = min(curr_x + dash_length, end_x)
                    cv2.line(img, (curr_x, target_y), (next_x, target_y), color, 2)
                    curr_x += dash_length + gap_length

            # --- TOOL: STANDARD HORIZONTAL LINE ---
            elif "horizontal_line" in drawing_tool:
                swing_type = from_candle.get("swing_type", "").lower()
                target_y = int(from_candle.get("draw_top", 0)) if "high" in swing_type else int(from_candle.get("draw_bottom", 0))
                cv2.line(img, (start_x, target_y), (end_x, target_y), color, 2)

        # Delete all patterns that were marked for deletion
        for p_name in patterns_to_delete:
            if p_name in patterns:
                del patterns[p_name]

        return img

    def identify_selected(target_data_tf, new_key, poi_config):
        """
        Filters pattern records based on extreme or non-extreme values of a specific define_n.
        Now checks pattern_entry candles to determine which swing types to process.
        Config format: 
            "multiple_selection": "define_3_extreme" or "define_3_non_extreme"
            "max_selection": 2 (optional) - limits to at most N patterns with the target define_n
        
        If max_selection is specified, it will keep at most N patterns, prioritizing the most
        extreme ones (including ties at the cutoff price level). If there are multiple patterns
        at the same price level as the Nth pattern, all of them are kept.
        If max_selection is missing or 0, it keeps only the most extreme pattern(s) (all ties at top).
        """
        if not poi_config or not isinstance(target_data_tf, dict):
            return target_data_tf

        pattern_key = f"{new_key}_patterns"
        patterns = target_data_tf.get(pattern_key, {})
        if not patterns:
            return target_data_tf

        # Get multiple_selection config
        selection_raw = poi_config.get("multiple_selection")
        if not selection_raw:
            return target_data_tf

        # Get max_selection config (default to 0 if not present)
        max_selection = poi_config.get("max_selection", 0)
        try:
            max_selection = int(max_selection)
        except (ValueError, TypeError):
            max_selection = 0

        # Parse multiple_selection: e.g., "define_3_extreme" -> target_key="define_3", mode="extreme"
        parts = selection_raw.split("_")
        if len(parts) < 3:
            return target_data_tf

        target_define_key = f"{parts[0]}_{parts[1]}"  # e.g., "define_3"
        mode = parts[2].lower()  # "extreme" or "non"
        if mode == "non":
            mode = "non_extreme"

        # Initialize patterns_to_keep as empty list at the beginning
        patterns_to_keep = []
        
        # STEP 1: Find all pattern_entry candles and determine which swing types exist
        pattern_entry_swing_types = set()
        pattern_entry_candles = {}
        
        for p_name, family in patterns.items():
            # Find the candle with pattern_entry: True
            pattern_entry_candle = next((c for c in family if c.get("pattern_entry") is True), None)
            
            if pattern_entry_candle:
                swing_type = pattern_entry_candle.get("swing_type", "").lower()
                if swing_type:
                    pattern_entry_swing_types.add(swing_type)
                    pattern_entry_candles[p_name] = {
                        "swing_type": swing_type,
                        "candle": pattern_entry_candle
                    }

        # STEP 2: If no pattern_entry candles found, process all patterns (original behavior)
        # Otherwise, only process patterns that match the swing types found in pattern_entry candles
        eligible_patterns = []
        
        for p_name, family in patterns.items():
            # Find the candle in this pattern that has target_define_key: True
            target_candle = next((c for c in family if c.get(target_define_key) is True), None)
            
            if target_candle:
                # Determine swing type from target_candle
                swing_type = target_candle.get("swing_type", "").lower()
                
                # If we have pattern_entry candles, only include patterns with matching swing types
                if pattern_entry_swing_types and swing_type not in pattern_entry_swing_types:
                    continue
                
                # Determine which price to look at based on swing type
                if "high" in swing_type:
                    price = target_candle.get("high")
                else:
                    price = target_candle.get("low")
                
                if price is not None:
                    eligible_patterns.append({
                        "name": p_name,
                        "price": price,
                        "swing_type": swing_type,
                        "candle_number": target_candle.get("candle_number"),
                        "full_candle": target_candle  # Store reference for potential future use
                    })

        # If no eligible patterns found, return unchanged
        if not eligible_patterns:
            return target_data_tf

        # Group patterns by swing_type
        patterns_by_type = {}
        for p in eligible_patterns:
            swing_type = p["swing_type"]
            if swing_type not in patterns_by_type:
                patterns_by_type[swing_type] = []
            patterns_by_type[swing_type].append(p)

        # Process each swing type independently
        for swing_type, type_patterns in patterns_by_type.items():
            # Determine the swing type category
            is_high_type = "high" in swing_type
            
            # Sort patterns for this swing type by how extreme they are (most extreme first)
            if is_high_type:
                if mode == "extreme":
                    # For highs in extreme mode: highest price is most extreme
                    sorted_patterns = sorted(type_patterns, key=lambda x: x["price"], reverse=True)
                else:  # non_extreme
                    # For highs in non-extreme mode: lowest price is most extreme
                    sorted_patterns = sorted(type_patterns, key=lambda x: x["price"])
            else:
                if mode == "extreme":
                    # For lows in extreme mode: lowest price is most extreme
                    sorted_patterns = sorted(type_patterns, key=lambda x: x["price"])
                else:  # non_extreme
                    # For lows in non-extreme mode: highest price is most extreme
                    sorted_patterns = sorted(type_patterns, key=lambda x: x["price"], reverse=True)

            # Apply max_selection logic for this swing type
            if max_selection > 0 and len(sorted_patterns) > max_selection:
                # We need to limit to at most max_selection patterns for this swing type
                
                # Take the top max_selection patterns
                top_n_patterns = sorted_patterns[:max_selection]
                
                # Get the price of the last pattern we're including
                last_price = top_n_patterns[-1]["price"]
                
                # Include any additional patterns at the same price level as the last included
                for p in sorted_patterns[max_selection:]:
                    if p["price"] == last_price:
                        top_n_patterns.append(p)
                    else:
                        break
                
                patterns_to_keep.extend([p["name"] for p in top_n_patterns])
            else:
                # No max_selection or we have fewer than max - keep all patterns for this swing type
                patterns_to_keep.extend([p["name"] for p in sorted_patterns])

        # Remove duplicate pattern names (in case a pattern appears in multiple swing types - shouldn't happen)
        patterns_to_keep = list(set(patterns_to_keep))

        # 4. Remove all patterns that aren't in our keep list
        patterns_to_remove = [p_name for p_name in patterns.keys() if p_name not in patterns_to_keep]
        
        for p_name in patterns_to_remove:
            if p_name in patterns:
                del patterns[p_name]

        return target_data_tf
    
    def identify_swing_mitigation_between_definitions(target_data_tf, new_key, original_candles, poi_config):
        """
        Checks for swing violations between multiple pairs of definitions (sender and receiver).
        The config expects a comma-separated string: "define_1_define_3, define_4_define_10"
        If any candle between a pair matches the receiver's swing_type and violates the price, 
        the pattern is removed.
        """
        if not poi_config or not isinstance(target_data_tf, dict):
            return

        pattern_key = f"{new_key}_patterns"
        patterns = target_data_tf.get(pattern_key, {})
        from_sub = poi_config.get("from_subject")
        
        # Get the raw string, e.g., "define_1_define_3, define_2_define_4"
        restrict_raw = poi_config.get("restrict_swing_mitigation_between_definitions")
        if not restrict_raw:
            return

        # Split by comma to handle multiple pairs
        restrict_pairs = [p.strip() for p in restrict_raw.split(",") if p.strip()]
        patterns_to_remove = []

        for p_name, family in patterns.items():
            from_candle = next((c for c in family if c.get(from_sub) is True), None)
            if not from_candle:
                continue

            # Determine target price level once per pattern based on from_subject
            target_swingtype = from_candle.get("swing_type", "").lower()
            if "high" in target_swingtype:
                price_key = poi_config.get("subject_is_swinghigh_or_lowerhigh", "low")
            else:
                price_key = poi_config.get("subject_is_swinglow_or_higherlow", "high")

            clean_key = price_key.replace("_price", "")
            target_price = from_candle.get(clean_key)
            
            if target_price is None:
                continue

            is_mitigated = False

            # Evaluate each pair defined in the config
            for pair_str in restrict_pairs:
                parts = pair_str.split("_")
                # Expecting format: define, N, define, M -> 4 parts
                if len(parts) < 4:
                    continue
                
                sender_key = f"{parts[0]}_{parts[1]}"
                receiver_key = f"{parts[2]}_{parts[3]}"

                sender_candle = next((c for c in family if c.get(sender_key) is True), None)
                receiver_candle = next((c for c in family if c.get(receiver_key) is True), None)

                if not sender_candle or not receiver_candle:
                    continue

                s_num = sender_candle.get("candle_number")
                r_num = receiver_candle.get("candle_number")
                receiver_swing_type = receiver_candle.get("swing_type", "").lower()
                
                # Define search range (exclusive)
                start_range = min(s_num, r_num) + 1
                end_range = max(s_num, r_num) - 1

                # Scan range for violations
                for oc in original_candles:
                    if not isinstance(oc, dict):
                        continue
                    
                    c_num = oc.get("candle_number")
                    if start_range <= c_num <= end_range:
                        current_swing = oc.get("swing_type", "").lower()
                        
                        # Match the swing type of the receiver
                        if current_swing == receiver_swing_type:
                            if receiver_swing_type == "swing_low":
                                v_low = oc.get("low")
                                if v_low is not None and v_low < target_price:
                                    is_mitigated = True
                                    break
                            elif receiver_swing_type == "swing_high":
                                v_high = oc.get("high")
                                if v_high is not None and v_high > target_price:
                                    is_mitigated = True
                                    break
                
                if is_mitigated:
                    break # No need to check other pairs for this pattern if one triggered

            if is_mitigated:
                patterns_to_remove.append(p_name)

        # Clean up patterns
        for p_name in patterns_to_remove:
            del patterns[p_name]

        return target_data_tf

    def draw_definition_tools(img, target_data_tf, pattern_key, identify_config):
        """
        Draws visual markers for definitions as HORIZONTAL LINES with optional text labels.
        If swept: draws horizontal line from define candle's price level across to sweeper candle
        If not swept: draws horizontal line from define candle extending to the right edge
        
        Now checks account management configuration to determine if drawing is enabled for each define_n.
        Supports both solid and dashed lines based on drawing_tool setting.
        Adds centered text labels above/below the line based on swing type, but ONLY for swept lines.
        """
        if not identify_config or img is None:
            return img
        
        patterns = target_data_tf.get(pattern_key, {})
        img_height, img_width = img.shape[:2]
        
        #print(f"DRAWING DEFINITION TOOLS for {pattern_key}")
        
        total_families = 0
        total_defines = 0
        swept_count = 0
        unswept_count = 0
        skipped_count = 0
        disabled_count = 0
        text_drawn_count = 0
        
        for family_name, family in patterns.items():
            if not isinstance(family, list):
                #print(f"  ⚠️ Family '{family_name}' is not a list, skipping")
                continue
            
            total_families += 1
            #print(f"\n  📁 Family: {family_name} ({len(family)} candles)")
            
            # First, build a map of sweeper candles by their candle_number for easy lookup
            sweeper_by_number = {}  # {sweeper_candle_number: sweeper_candle}
            
            # Also build a map of which sweepers map to which victims
            # This is based on the sweeper's swept_victims field
            sweeper_for_victim = {}  # {victim_candle_number: sweeper_candle}
            
            for candle in family:
                if not isinstance(candle, dict):
                    continue
                
                candle_num = candle.get("candle_number")
                if candle_num is None:
                    continue
                
                # If this candle is a sweeper (has is_liquidity_sweep = True)
                if candle.get("is_liquidity_sweep") is True:
                    sweeper_by_number[candle_num] = candle
                    
                    # Map this sweeper to all its victims
                    swept_victims = candle.get("swept_victims", [])
                    if swept_victims:
                        for victim_num in swept_victims:
                            sweeper_for_victim[victim_num] = candle
                    # Also handle single victim case
                    single_victim = candle.get("swept_victim_number")
                    if single_victim and single_victim not in sweeper_for_victim:
                        sweeper_for_victim[single_victim] = candle
            
            # Now draw for each define candle
            family_defines = 0
            family_swept = 0
            family_unswept = 0
            family_disabled = 0
            family_text_drawn = 0
            
            for candle in family:
                if not isinstance(candle, dict):
                    continue
                
                # Check if this candle is a define (any define_n)
                define_name = None
                for key in candle.keys():
                    if key.startswith("define_") and candle[key] is True:
                        define_name = key
                        break
                
                if not define_name:
                    continue
                
                family_defines += 1
                total_defines += 1
                
                # Get candle details
                candle_num = candle.get("candle_number", "???")
                swing_type = candle.get("swing_type", "").lower()
                
                #print(f"\n    🔍 Processing {define_name} (Candle #{candle_num})")
                #print(f"       Swing type: {swing_type}")
                
                # --- ACCOUNT MANAGEMENT CHECK ---
                # Check if this specific define_n is enabled for drawing
                # First check define-specific settings in identify_config
                define_settings = identify_config.get(define_name, {})
                
                # If define-specific settings exist, check if drawing is enabled
                if define_settings:
                    drawing_enabled = define_settings.get("enable_drawing", True)  # Default to True if not specified
                    #print(f"       📋 Account management for {define_name}: enable_drawing = {drawing_enabled}")
                    
                    if not drawing_enabled:
                        #print(f"       ⏭️ Skipped: {define_name} drawing disabled in account management")
                        disabled_count += 1
                        family_disabled += 1
                        continue
                    
                    # Get text label if available
                    text_label = define_settings.get("text", "")
                    #print(f"       📝 Text label: '{text_label}'")
                else:
                    # No specific settings for this define_n, assume drawing is enabled
                    #print(f"       ℹ️ No account management settings for {define_name}, using default (enabled)")
                    text_label = ""  # No text label by default
                
                # Get drawing tool preference for this specific define
                drawing_tool = define_settings.get("tool", identify_config.get("drawing_tool", "horizontal_line"))
                #print(f"       🖌️ Drawing tool: {drawing_tool}")
                
                # Check all possible swept indicators
                swept_by_num = candle.get("swept_by_candle_number")
                swept_by_liquidity = candle.get("swept_by_liquidity")
                
                # Check if this candle is a victim (has a sweeper mapped to it)
                is_victim = candle_num in sweeper_for_victim
                
                #print(f"       swept_by_candle_number: {swept_by_num}")
                #print(f"       swept_by_liquidity: {swept_by_liquidity}")
                #print(f"       is_victim (has sweeper mapped): {is_victim}")
                
                # Determine the Y-coordinate (price level) based on swing type
                # This is the horizontal line level
                if "swing_high" in swing_type:
                    # For higher high, draw from the HIGH of the candle
                    line_y = int(candle.get("draw_top", candle.get("candle_top", 0)))
                    line_desc = f"high at Y={line_y}"
                    # Start from the RIGHT side of the candle
                    start_x = int(candle.get("draw_right", candle.get("candle_right", 0)))
                    text_position = "above"  # Text should be above the line for higher high
                elif "swing_low" in swing_type:
                    # For lower low, draw from the LOW of the candle
                    line_y = int(candle.get("draw_bottom", candle.get("candle_bottom", img_height)))
                    line_desc = f"low at Y={line_y}"
                    # Start from the RIGHT side of the candle
                    start_x = int(candle.get("draw_right", candle.get("candle_right", 0)))
                    text_position = "below"  # Text should be below the line for lower low
                else:
                    #print(f"        Skipped: Unknown swing type '{swing_type}'")
                    skipped_count += 1
                    continue
                
                #print(f"       Horizontal line level: {line_desc}")
                #print(f"       Start X: {start_x}")
                #print(f"       Text position: {text_position}")
                
                # Determine if swept and find sweeper
                sweeper = None
                end_x = img_width  # Default to right edge
                end_desc = "right edge"
                is_swept = False
                
                # Priority 1: Check if this candle has a sweeper mapped to it via sweeper_for_victim
                if candle_num in sweeper_for_victim:
                    sweeper = sweeper_for_victim[candle_num]
                    sweeper_num = sweeper.get("candle_number", "???")
                    #print(f"       ✅ Swept via victim mapping to sweeper #{sweeper_num}")
                    is_swept = True
                
                # Priority 2: Check direct swept_by_candle_number that exists in sweeper_by_number
                elif swept_by_num and swept_by_num in sweeper_by_number:
                    sweeper = sweeper_by_number[swept_by_num]
                    #print(f"       ✅ Swept via direct swept_by_candle_number={swept_by_num}")
                    is_swept = True
                
                if sweeper:
                    # If swept, draw horizontal line to the sweeper candle's LEFT side
                    sweeper_num = sweeper.get("candle_number", "???")
                    
                    # Get the sweeper's left side coordinate
                    # For sweepers, we want to draw to their left side (where they start)
                    end_x = int(sweeper.get("draw_left", sweeper.get("candle_left", img_width)))
                    
                    # Make sure we're drawing to the LEFT of the sweeper (earlier in time)
                    # If the sweeper is to the left of the victim (shouldn't happen by logic), adjust
                    if end_x < start_x:
                        # Sweeper is to the left, draw to its right side instead
                        end_x = int(sweeper.get("draw_right", sweeper.get("candle_right", img_width)))
                        end_desc = f"sweeper #{sweeper_num} right side at X={end_x}"
                    else:
                        end_desc = f"sweeper #{sweeper_num} left side at X={end_x}"
                    
                    #print(f"       📍 Swept: drawing horizontal line to {end_desc}")
                    swept_count += 1
                    family_swept += 1
                else:
                    # If not swept, draw horizontal line to right edge
                    #print(f"       ➡️ Not swept: drawing horizontal line to right edge at X={end_x}")
                    unswept_count += 1
                    family_unswept += 1
                
                # Draw the line based on drawing tool preference
                if "dashed_horizontal_line" in drawing_tool:
                    # Draw DASHED horizontal line
                    dash_length = 10
                    gap_length = 5
                    curr_x = start_x
                    
                    while curr_x < end_x:
                        next_x = min(curr_x + dash_length, end_x)
                        cv2.line(img, (curr_x, line_y), (next_x, line_y), (0, 0, 0), 1, cv2.LINE_AA)
                        curr_x += dash_length + gap_length
                    
                    #print(f"       🖍️ Drew DASHED line from X={start_x} to X={end_x}")
                else:
                    # Draw SOLID horizontal line (default)
                    cv2.line(img, (start_x, line_y), (end_x, line_y), (0, 0, 0), 1, cv2.LINE_AA)
                    #print(f"       🖍️ Drew SOLID line from X={start_x} to X={end_x}")
                
                # Draw text label ONLY if the line is swept (has a sweeper)
                if text_label and is_swept:
                    # Calculate center X coordinate of the line
                    center_x = (start_x + end_x) // 2
                    
                    # Calculate Y coordinate based on text position
                    if text_position == "above":
                        # Place text above the line (5 pixels above)
                        text_y = line_y - 5
                        text_bg_y1 = text_y - 15
                        text_bg_y2 = text_y + 5
                    else:  # below
                        # Place text below the line (15 pixels below to account for text height)
                        text_y = line_y + 15
                        text_bg_y1 = text_y - 15
                        text_bg_y2 = text_y + 5
                    
                    # Get text size
                    font = cv2.FONT_HERSHEY_SIMPLEX
                    font_scale = 0.4
                    thickness = 1
                    (text_width, text_height), baseline = cv2.getTextSize(text_label, font, font_scale, thickness)
                    
                    # Calculate text position to center it horizontally
                    text_x = center_x - (text_width // 2)
                    
                    # Draw white background rectangle for better readability
                    padding = 2
                    bg_x1 = text_x - padding
                    bg_y1 = text_y - text_height - padding
                    bg_x2 = text_x + text_width + padding
                    bg_y2 = text_y + padding
                    
                    # Ensure background stays within image bounds
                    bg_x1 = max(0, bg_x1)
                    bg_y1 = max(0, bg_y1)
                    bg_x2 = min(img_width, bg_x2)
                    bg_y2 = min(img_height, bg_y2)
                    
                    # Draw background rectangle
                    cv2.rectangle(img, (bg_x1, bg_y1), (bg_x2, bg_y2), (255, 255, 255), -1)
                    
                    # Draw text in black
                    cv2.putText(img, text_label, (text_x, text_y), font, font_scale, (0, 0, 0), thickness, cv2.LINE_AA)
                    
                    #print(f"       📝 Drew text '{text_label}' at center X={center_x}, Y={text_y} ({text_position} line)")
                    text_drawn_count += 1
                    family_text_drawn += 1
        return img
  
    def identify_pending_prices(target_data_tf, new_key, record_config, dev_base_path, new_folder_name):
        """
        Saves limit orders into a pending_orders folder INSIDE the specific new_filename folder.
        Path: dev_base_path/new_folder_name/pending_orders/limit_orders.json
        Also adds order_type flag to the entry candle in the original data structure
        
        Only records if record_hitler_order is False or not present
        """
        if not record_config:
            return

        # Check if hitler order recording is enabled - if true, skip recording here
        if record_config.get("record_hitler_order", False):
            return

        pattern_key = f"{new_key}_patterns"
        patterns = target_data_tf.get(pattern_key, {})
        
        if not patterns:
            return
        
        pending_list = []
        price_map = {
            "low_price": "low",
            "high_price": "high",
            "open_price": "open",
            "close_price": "close",
            "center_price": "center_price"  # Added center_price support
        }
        
        # Updated Path Logic: Inside the new_folder_name directory
        orders_dir = os.path.join(dev_base_path, new_folder_name, "pending_orders")
        os.makedirs(orders_dir, exist_ok=True)
        orders_file = os.path.join(orders_dir, "limit_orders.json")

        for p_name, family in patterns.items():
            # Check for pending_entry_level
            origin_candle = next((c for c in family if c.get("pending_entry_level") is True), None)
            
            if origin_candle:
                order_data = {
                    "symbol": origin_candle.get("symbol", "unknown"),
                    "timeframe": origin_candle.get("timeframe", "unknown"),
                    "risk_reward": record_config.get("risk_reward", 0),
                    "order_type": "unknown",
                    "entry": 0,
                    "exit": 0,
                    "target": 0
                }

                for role in ["entry", "exit", "target"]:
                    role_cfg = record_config.get(role, {})
                    subject_key = role_cfg.get("subject")
                    
                    if subject_key:
                        target_candle = next((c for c in family if c.get(subject_key) is True), None)
                        if target_candle:
                            swing_type = target_candle.get("swing_type", "").lower()
                            
                            price_attr_raw = ""
                            if "high" in swing_type:
                                price_attr_raw = role_cfg.get("subject_is_swinghigh_or_lowerhigh")
                            elif "low" in swing_type:
                                price_attr_raw = role_cfg.get("subject_is_swinglow_or_higherlow")

                            # Check if price_attr_raw is "center_price" or map to actual key
                            if price_attr_raw == "center_price":
                                # Calculate center price if not already present in candle
                                if "center_price" not in target_candle:
                                    # Calculate as (high + low) / 2
                                    high = target_candle.get("high", 0)
                                    low = target_candle.get("low", 0)
                                    target_candle["center_price"] = (high + low) / 2 if high and low else 0
                                order_data[role] = target_candle.get("center_price", 0)
                            else:
                                actual_key = price_map.get(price_attr_raw, price_attr_raw)
                                if actual_key:
                                    order_data[role] = target_candle.get(actual_key, 0)
                
                entry_subject = record_config.get("entry", {}).get("subject")
                entry_candle = next((c for c in family if entry_subject and c.get(entry_subject) is True), origin_candle)
                
                e_swing = entry_candle.get("swing_type", "").lower()
                type_cfg = record_config.get("order_type", {})
                
                if "high" in e_swing:
                    order_data["order_type"] = type_cfg.get("subject_is_swinghigh_or_lowerhigh", "sell_limit")
                else:
                    order_data["order_type"] = type_cfg.get("subject_is_swinglow_or_higherlow", "buy_limit")
                
                # Add order_type flag to the origin candle (pending_entry_level candle)
                origin_candle["order_type"] = order_data["order_type"]
                
                # Also add order_type flag to the entry candle if it's different from origin_candle
                if entry_candle != origin_candle:
                    entry_candle["order_type"] = order_data["order_type"]

                pending_list.append(order_data)

        if pending_list:
            existing_orders = []
            if os.path.exists(orders_file):
                try:
                    with open(orders_file, 'r', encoding='utf-8') as f:
                        existing_orders = json.load(f)
                except Exception:
                    existing_orders = []

            existing_orders.extend(pending_list)
            
            with open(orders_file, 'w', encoding='utf-8') as f:
                json.dump(existing_orders, f, indent=4)

    def identify_hitler_prices(target_data_tf, new_key, record_config, dev_base_path, new_folder_name, target_data_full=None):
        """
        Saves hitler/POI entry information into a poi_entry.json file.
        Path: dev_base_path/new_folder_name/pending_orders/poi_entry.json
        Follows the same logic as identify_prices but targets Hitler/POI candles
        Records orders regardless of confirmation status
        Also adds order_type flag to the Hitler/POI candle in the original data structure
        
        If record_hitler_order is True, also records to limit_orders.json
        
        Adds hitler_poi_entry field:
        - If hit_from_above is True: entry = low price
        - If hit_from_below is True: entry = high price
        """
        if not record_config:
            return

        pattern_key = f"{new_key}_patterns"
        patterns = target_data_tf.get(pattern_key, {})
        
        if not patterns:
            return
        
        # Check if we should also record to limit_orders.json
        record_to_limit_orders = record_config.get("record_hitler_order", False)
        
        pending_poi_list = []
        limit_orders_list = []  # For storing orders to add to limit_orders.json
        price_map = {
            "low_price": "low",
            "high_price": "high",
            "open_price": "open",
            "close_price": "close",
            "center_price": "center_price"  # Added center_price support
        }
        
        # Path Logic: Inside the new_folder_name directory
        orders_dir = os.path.join(dev_base_path, new_folder_name, "pending_orders")
        os.makedirs(orders_dir, exist_ok=True)
        poi_file = os.path.join(orders_dir, "poi_entry.json")
        limit_orders_file = os.path.join(orders_dir, "limit_orders.json")

        for p_name, family in patterns.items():
            # Find the Hitler/POI candle instead of pending_entry_level
            hitler_candle = next((c for c in family if c.get("is_hitler_poi") is True or c.get("point_of_interest") is True), None)
            
            if hitler_candle:
                # Determine hitler_poi_entry based on hit direction
                hitler_poi_entry = None
                
                if hitler_candle.get("hit_from_above"):
                    # Price came from above to hit below -> entry is low price
                    hitler_poi_entry = hitler_candle.get("low")
                elif hitler_candle.get("hit_from_below"):
                    # Price came from below to hit above -> entry is high price
                    hitler_poi_entry = hitler_candle.get("high")
                
                poi_data = {
                    "symbol": hitler_candle.get("symbol", "unknown"),
                    "timeframe": hitler_candle.get("timeframe", "unknown"),
                    "risk_reward": record_config.get("risk_reward", 0),
                    "order_type": "unknown",
                    "entry": 0,
                    "exit": 0,
                    "target": 0,
                    "hitler_time": hitler_candle.get("time", ""),  # Additional field for hitler time
                    "hitler_poi_entry": hitler_poi_entry,  # New field based on hit direction
                    "hit_from_above": hitler_candle.get("hit_from_above", False),  # For debugging/verification
                    "hit_from_below": hitler_candle.get("hit_from_below", False)   # For debugging/verification
                }

                # Get entry, exit, and target prices using the same logic as identify_prices
                for role in ["entry", "exit", "target"]:
                    role_cfg = record_config.get(role, {})
                    subject_key = role_cfg.get("subject")
                    
                    if subject_key:
                        target_candle = next((c for c in family if c.get(subject_key) is True), None)
                        if target_candle:
                            swing_type = target_candle.get("swing_type", "").lower()
                            price_attr_raw = ""
                            if "high" in swing_type:
                                price_attr_raw = role_cfg.get("subject_is_swinghigh_or_lowerhigh")
                            elif "low" in swing_type:
                                price_attr_raw = role_cfg.get("subject_is_swinglow_or_higherlow")

                            # Check if price_attr_raw is "center_price" or map to actual key
                            if price_attr_raw == "center_price":
                                # Calculate center price if not already present in candle
                                if "center_price" not in target_candle:
                                    # Calculate as (high + low) / 2
                                    high = target_candle.get("high", 0)
                                    low = target_candle.get("low", 0)
                                    target_candle["center_price"] = (high + low) / 2 if high and low else 0
                                poi_data[role] = target_candle.get("center_price", 0)
                            else:
                                actual_key = price_map.get(price_attr_raw, price_attr_raw)
                                if actual_key:
                                    poi_data[role] = target_candle.get(actual_key, 0)
                
                # Determine order type using the same logic as identify_prices
                entry_subject = record_config.get("entry", {}).get("subject")
                entry_candle = next((c for c in family if entry_subject and c.get(entry_subject) is True), hitler_candle)
                
                e_swing = entry_candle.get("swing_type", "").lower()
                type_cfg = record_config.get("order_type", {})
                
                if "high" in e_swing:
                    poi_data["order_type"] = type_cfg.get("subject_is_swinghigh_or_lowerhigh", "sell_limit")
                else:
                    poi_data["order_type"] = type_cfg.get("subject_is_swinglow_or_higherlow", "buy_limit")
                
                # Add order_type flag to the Hitler/POI candle
                hitler_candle["order_type"] = poi_data["order_type"]
                # Also add hitler_poi_entry to the candle for reference
                hitler_candle["hitler_poi_entry"] = hitler_poi_entry
                
                # Also add order_type flag to the entry candle if it's different from hitler_candle
                if entry_candle != hitler_candle:
                    entry_candle["order_type"] = poi_data["order_type"]

                pending_poi_list.append(poi_data)
                
                # If record_hitler_order is True, also prepare for limit_orders.json
                if record_to_limit_orders:
                    # Create a copy WITH the hitler_time and hitler_poi_entry fields for limit orders
                    limit_order_data = {
                        "symbol": poi_data["symbol"],
                        "timeframe": poi_data["timeframe"],
                        "risk_reward": poi_data["risk_reward"],
                        "order_type": poi_data["order_type"],
                        "entry": poi_data["entry"],
                        "exit": poi_data["exit"],
                        "target": poi_data["target"],
                        "hitler_time": poi_data["hitler_time"],  # Include hitler_time field
                        "hitler_poi_entry": poi_data["hitler_poi_entry"],  # Include hitler_poi_entry field
                        "hit_from_above": poi_data["hit_from_above"],  # Include for context
                        "hit_from_below": poi_data["hit_from_below"]   # Include for context
                    }
                    limit_orders_list.append(limit_order_data)

        # Save to poi_entry.json
        if pending_poi_list:
            existing_poi = []
            if os.path.exists(poi_file):
                try:
                    with open(poi_file, 'r', encoding='utf-8') as f:
                        existing_poi = json.load(f)
                except: 
                    existing_poi = []
            
            # Create a dictionary keyed by (symbol, timeframe, hitler_time) to avoid duplicates
            poi_dict = {}
            
            # Add existing entries to dictionary
            for entry in existing_poi:
                key = (entry.get("symbol"), entry.get("timeframe"), entry.get("hitler_time"))
                poi_dict[key] = entry
            
            # Add new entries (will overwrite if same key exists)
            for entry in pending_poi_list:
                key = (entry.get("symbol"), entry.get("timeframe"), entry.get("hitler_time"))
                poi_dict[key] = entry
            
            # Convert back to list
            merged_poi = list(poi_dict.values())
            
            with open(poi_file, 'w', encoding='utf-8') as f:
                json.dump(merged_poi, f, indent=4)
        
        # Save to limit_orders.json if record_hitler_order is True
        if record_to_limit_orders and limit_orders_list:
            existing_limit_orders = []
            if os.path.exists(limit_orders_file):
                try:
                    with open(limit_orders_file, 'r', encoding='utf-8') as f:
                        existing_limit_orders = json.load(f)
                except Exception:
                    existing_limit_orders = []
            
            existing_limit_orders.extend(limit_orders_list)
            
            with open(limit_orders_file, 'w', encoding='utf-8') as f:
                json.dump(existing_limit_orders, f, indent=4)

    def mark_orders_with_candle_after_poi_and_switch_order_type(dev_base_path, new_folder_name, target_data_tf, new_key, symbol, poi_config=None, record_config=None):
        """
        Combined function that:
        1. Marks orders in limit_orders.json and poi_entry.json if they have a candle_after_poi record
        2. Modifies existing limit orders based on switch_order_type configuration
        3. If candle_after_poi_record_only is True, removes orders without candle_after_poi from limit_orders.json
        
        This function should be called after identify_pending_prices and identify_hitler_prices
        have been executed, but before the final JSON writes.
        
        It locates patterns that have candles with candle_after_poi=True and then finds the
        corresponding orders in the order files to mark them with candle_after_poi_exists=True.
        Additionally, it applies order type switching rules from the POI configuration.
        
        Args:
            dev_base_path: Base development path
            new_folder_name: Folder name for the current processing
            target_data_tf: Timeframe-specific data containing patterns
            new_key: The key for the current pattern family
            symbol: Current symbol being processed
            poi_config: POI configuration containing switch_order_type rules (optional)
            record_config: Record configuration containing candle_after_poi_record_only flag (optional)
        """
        if not target_data_tf:
            return False
        
        pattern_key = f"{new_key}_patterns"
        patterns = target_data_tf.get(pattern_key, {})
        
        if not patterns:
            return False
        
        # Paths to order files
        orders_dir = os.path.join(dev_base_path, new_folder_name, "pending_orders")
        if not os.path.exists(orders_dir):
            return False
        
        limit_orders_file = os.path.join(orders_dir, "limit_orders.json")
        poi_entry_file = os.path.join(orders_dir, "poi_entry.json")
        
        # Track if any modifications were made
        modified = False
        
        # =================================================================
        # PART 1: Get switch_order_type configuration (if available)
        # =================================================================
        switch_rules = {}
        if poi_config:
            candles_after_config = poi_config.get("candles_after_poi_confirmation", {})
            switch_rules = candles_after_config.get("switch_order_type", {})
        
        # =================================================================
        # PART 2: Get candle_after_poi_record_only setting
        # =================================================================
        candle_after_poi_record_only = False
        if record_config:
            candle_after_poi_record_only = record_config.get("candle_after_poi_record_only", False)
        
        # =================================================================
        # PART 3: Load existing orders for modifications
        # =================================================================
        limit_orders = []
        poi_entries = []
        
        if os.path.exists(limit_orders_file):
            try:
                with open(limit_orders_file, 'r', encoding='utf-8') as f:
                    limit_orders = json.load(f)
            except Exception:
                limit_orders = []
        
        if os.path.exists(poi_entry_file):
            try:
                with open(poi_entry_file, 'r', encoding='utf-8') as f:
                    poi_entries = json.load(f)
            except Exception:
                poi_entries = []
        
        # =================================================================
        # PART 4: Track which orders have candle_after_poi for filtering
        # =================================================================
        orders_with_candle_after_poi = set()
        
        # =================================================================
        # PART 5: Process each pattern family
        # =================================================================
        for p_name, family in patterns.items():
            # Find all candles in the family that have candle_after_poi=True
            candles_after_poi = [c for c in family if isinstance(c, dict) and c.get("candle_after_poi") is True]
            
            # Get the order type and entry price from the pattern
            # First, find the Hitler/POI candle or pending entry level candle
            hitler_candle = next((c for c in family if c.get("is_hitler_poi") is True or c.get("point_of_interest") is True), None)
            pending_candle = next((c for c in family if c.get("pending_entry_level") is True), None)
            
            # Determine which candle to use for order identification
            source_candle = hitler_candle if hitler_candle else pending_candle
            
            if not source_candle:
                continue
            
            # Extract order identification fields
            symbol_name = source_candle.get("symbol", symbol)
            timeframe = source_candle.get("timeframe", "unknown")
            order_type = source_candle.get("order_type", "")
            entry_price = None
            hitler_time = source_candle.get("time", "")  # For POI entry matching
            
            # Create a unique identifier for this order (for tracking)
            order_identifier = f"{symbol_name}_{timeframe}_{order_type}_{entry_price}"
            
            # Try to get entry price from various sources
            # Check if there's an entry candle in the family
            entry_candle = next((c for c in family if c.get("entry") is True), None)
            if entry_candle:
                # Determine which price to use based on swing type
                swing_type = entry_candle.get("swing_type", "").lower()
                if "high" in swing_type:
                    entry_price = entry_candle.get("high")
                elif "low" in swing_type:
                    entry_price = entry_candle.get("low")
            
            if not entry_price:
                # Fall back to source candle's high/low based on order type
                if "sell" in order_type.lower():
                    entry_price = source_candle.get("high")
                elif "buy" in order_type.lower():
                    entry_price = source_candle.get("low")
            
            if not entry_price:
                # Last resort: use any price from source candle
                entry_price = source_candle.get("close") or source_candle.get("open") or 0
            
            # Also get target and exit prices for better matching
            target_candle = next((c for c in family if c.get("target") is True), None)
            exit_candle = next((c for c in family if c.get("exit") is True), None)
            
            target_price = None
            exit_price = None
            
            if target_candle:
                swing_type = target_candle.get("swing_type", "").lower()
                if "high" in swing_type:
                    target_price = target_candle.get("high")
                elif "low" in swing_type:
                    target_price = target_candle.get("low")
            
            if exit_candle:
                swing_type = exit_candle.get("swing_type", "").lower()
                if "high" in swing_type:
                    exit_price = exit_candle.get("high")
                elif "low" in swing_type:
                    exit_price = exit_candle.get("low")
            
            # =================================================================
            # MARK IN LIMIT_ORDERS.JSON (with candle_after_poi info)
            # =================================================================
            if limit_orders and isinstance(limit_orders, list):
                orders_modified = False
                
                for idx, order in enumerate(limit_orders):
                    # Check if this order matches our pattern
                    order_symbol = order.get("symbol", "")
                    order_timeframe = order.get("timeframe", "")
                    order_type_match = order.get("order_type", "")
                    order_entry = order.get("entry", 0)
                    order_target = order.get("target", 0)
                    order_exit = order.get("exit", 0)
                    
                    # Create a matching score to ensure we find the right order
                    match_score = 0
                    
                    # Primary matches (required for high confidence)
                    if order_symbol == symbol_name:
                        match_score += 10
                    if order_timeframe == timeframe:
                        match_score += 10
                    if order_type_match == order_type:
                        match_score += 10
                    
                    # Secondary matches (increase confidence)
                    if order_entry and entry_price and abs(order_entry - entry_price) < (entry_price * 0.001):  # Within 0.1%
                        match_score += 5
                    
                    if order_target and target_price and abs(order_target - target_price) < (target_price * 0.001):
                        match_score += 3
                    
                    if order_exit and exit_price and abs(order_exit - exit_price) < (exit_price * 0.001):
                        match_score += 3
                    
                    # If match score is high enough (at least 20 points), mark the order
                    if match_score >= 20:
                        # Track this order as having candle_after_poi
                        order_identifier = f"{order_symbol}_{order_timeframe}_{order_type_match}_{order_entry}"
                        orders_with_candle_after_poi.add(order_identifier)
                        
                        # Mark candle_after_poi if it exists
                        if candles_after_poi:
                            if not order.get("candle_after_poi_exists"):
                                order["candle_after_poi_exists"] = True
                                # Add additional metadata about the candle after POI
                                order["candle_after_poi_count"] = len(candles_after_poi)
                                
                                # Add direction information from the first candle after POI
                                first_candle = candles_after_poi[0]
                                if first_candle.get("candle_after_poi_above_entry"):
                                    order["candle_after_poi_above_entry"] = True
                                if first_candle.get("candle_after_poi_below_entry"):
                                    order["candle_after_poi_below_entry"] = True
                                if first_candle.get("continued_direction_after_poi"):
                                    order["candle_after_poi_continued_direction"] = True
                                
                                orders_modified = True
                                modified = True
                        
                        # Apply order type switching rules
                        if switch_rules:
                            current_order_type = order.get("order_type", "")
                            
                            # Check each rule in switch_order_type
                            for rule_key, rule_config in switch_rules.items():
                                if not isinstance(rule_config, dict):
                                    continue
                                
                                existing_type = rule_config.get("if_existing_is", "")
                                switch_to_type = rule_config.get("switch_to", "")
                                
                                # Skip if either value is empty
                                if not existing_type or not switch_to_type:
                                    continue
                                
                                # Check if current order type matches the rule
                                if current_order_type == existing_type:
                                    order["order_type"] = switch_to_type
                                    order["order_type_switched"] = True
                                    order["order_type_switched_from"] = existing_type
                                    order["order_type_switched_by_rule"] = rule_key
                                    order["order_type_switched_because_candle_after_poi"] = True
                                    
                                    orders_modified = True
                                    modified = True
                                    break  # Once a rule matches, stop checking other rules for this order
                
                # Write back if modified (but before filtering)
                if orders_modified:
                    with open(limit_orders_file, 'w', encoding='utf-8') as f:
                        json.dump(limit_orders, f, indent=4)
                    
                    marked_count = sum(1 for o in limit_orders if o.get("candle_after_poi_exists"))
                    switched_count = sum(1 for o in limit_orders if o.get("order_type_switched") is True)
                    
            
            # =================================================================
            # MARK IN POI_ENTRY.JSON (with candle_after_poi info)
            # =================================================================
            if poi_entries and isinstance(poi_entries, list):
                entries_modified = False
                
                for entry in poi_entries:
                    # Check if this POI entry matches our pattern
                    entry_symbol = entry.get("symbol", "")
                    entry_timeframe = entry.get("timeframe", "")
                    entry_order_type = entry.get("order_type", "")
                    entry_price_value = entry.get("entry", 0)
                    entry_hitler_time = entry.get("hitler_time", "")
                    entry_target = entry.get("target", 0)
                    entry_exit = entry.get("exit", 0)
                    
                    # Create a matching score
                    match_score = 0
                    
                    # Primary matches
                    if entry_symbol == symbol_name:
                        match_score += 10
                    if entry_timeframe == timeframe:
                        match_score += 10
                    if entry_order_type == order_type:
                        match_score += 10
                    
                    # Time-based matching (strong indicator for POI entries)
                    if hitler_time and entry_hitler_time and hitler_time == entry_hitler_time:
                        match_score += 15
                    
                    # Price-based matching
                    if entry_price_value and entry_price and abs(entry_price_value - entry_price) < (entry_price * 0.001):
                        match_score += 5
                    
                    if entry_target and target_price and abs(entry_target - target_price) < (target_price * 0.001):
                        match_score += 3
                    
                    if entry_exit and exit_price and abs(entry_exit - exit_price) < (exit_price * 0.001):
                        match_score += 3
                    
                    # If match score is high enough, mark the POI entry
                    if match_score >= 20:
                        # Mark candle_after_poi if it exists
                        if candles_after_poi:
                            if not entry.get("candle_after_poi_exists"):
                                entry["candle_after_poi_exists"] = True
                                # Add additional metadata
                                entry["candle_after_poi_count"] = len(candles_after_poi)
                                
                                # Add direction information
                                first_candle = candles_after_poi[0]
                                if first_candle.get("candle_after_poi_above_entry"):
                                    entry["candle_after_poi_above_entry"] = True
                                if first_candle.get("candle_after_poi_below_entry"):
                                    entry["candle_after_poi_below_entry"] = True
                                if first_candle.get("continued_direction_after_poi"):
                                    entry["candle_after_poi_continued_direction"] = True
                                
                                entries_modified = True
                                modified = True
                        
                        # Apply order type switching rules to POI entries as well
                        if switch_rules:
                            current_order_type = entry.get("order_type", "")
                            
                            for rule_key, rule_config in switch_rules.items():
                                if not isinstance(rule_config, dict):
                                    continue
                                
                                existing_type = rule_config.get("if_existing_is", "")
                                switch_to_type = rule_config.get("switch_to", "")
                                
                                if not existing_type or not switch_to_type:
                                    continue
                                
                                if current_order_type == existing_type:
                                    entry["order_type"] = switch_to_type
                                    entry["order_type_switched"] = True
                                    entry["order_type_switched_from"] = existing_type
                                    entry["order_type_switched_by_rule"] = rule_key
                                    entry["order_type_switched_because_candle_after_poi"] = True
                                    
                                    entries_modified = True
                                    modified = True
                                    break
                
                # Write back if modified
                if entries_modified:
                    with open(poi_entry_file, 'w', encoding='utf-8') as f:
                        json.dump(poi_entries, f, indent=4)
                    
                    marked_count = sum(1 for e in poi_entries if e.get("candle_after_poi_exists"))
                    switched_count = sum(1 for e in poi_entries if e.get("order_type_switched") is True)
                    
        
        # =================================================================
        # PART 6: Filter limit_orders.json if candle_after_poi_record_only is True
        # =================================================================
        if candle_after_poi_record_only and limit_orders and isinstance(limit_orders, list):
            # Reload the latest limit_orders (in case they were modified above)
            if os.path.exists(limit_orders_file):
                try:
                    with open(limit_orders_file, 'r', encoding='utf-8') as f:
                        limit_orders = json.load(f)
                except Exception:
                    limit_orders = []
            
            if limit_orders:
                # Count orders before filtering
                original_count = len(limit_orders)
                
                # Filter: Keep only orders that have candle_after_poi_exists = True
                # Also keep orders that were marked as having candle_after_poi via our tracking
                filtered_orders = []
                
                for order in limit_orders:
                    # Check if order has candle_after_poi_exists flag
                    if order.get("candle_after_poi_exists") is True:
                        filtered_orders.append(order)
                    else:
                        # Also check if this order was tracked in our set
                        order_identifier = f"{order.get('symbol', '')}_{order.get('timeframe', '')}_{order.get('order_type', '')}_{order.get('entry', 0)}"
                        if order_identifier in orders_with_candle_after_poi:
                            filtered_orders.append(order)
                        else:
                            # Log the removal if needed (optional)
                            log(f"    🗑️ Removing limit order without candle_after_poi: {order.get('symbol')} {order.get('timeframe')} {order.get('order_type')} @ {order.get('entry')}")
                
                # Check if any orders were removed
                removed_count = original_count - len(filtered_orders)
                
                if removed_count > 0:
                    # Write back the filtered orders
                    with open(limit_orders_file, 'w', encoding='utf-8') as f:
                        json.dump(filtered_orders, f, indent=4)
                    
                    modified = True
        
        return modified
    
    def apply_hitler_poi_entry_condition_to_orders(dev_base_path, new_folder_name, record_config):
        """
        Applies conditions to replace exit or entry prices in limit orders based on hitler_poi_entry.
        
        Configuration format:
        "record_prices": {
            "record_hitler_order": true,
            "candle_after_poi_record_only": true,
            "hitler_poi_entry_condition": "behind_exit"  # or "beyond_exit", "behind_entry", "beyond_entry"
        }
        
        When condition is met, replaces the target price (exit or entry) with hitler_poi_entry value.
        """
        if not record_config:
            return False
        
        condition_cfg = record_config.get("hitler_poi_entry_condition", "")
        if not condition_cfg:
            return False
        
        # Parse condition
        condition_cfg = condition_cfg.lower()
        mode = "behind" if "behind" in condition_cfg else "beyond"
        target_type = "exit" if "exit" in condition_cfg else "entry"
        
        # Paths to order files
        orders_dir = os.path.join(dev_base_path, new_folder_name, "pending_orders")
        if not os.path.exists(orders_dir):
            return False
        
        limit_orders_file = os.path.join(orders_dir, "limit_orders.json")
        poi_entry_file = os.path.join(orders_dir, "poi_entry.json")
        
        modified = False
        
        # Helper function to apply condition logic
        def check_condition_and_replace(order_data, order_type, entry_price, exit_price, target_price, hitler_poi_entry, hit_from_above, hit_from_below):
            """
            Check if hitler_poi_entry meets the condition relative to target price,
            and if so, return the new value to replace.
            
            Returns:
                tuple: (should_replace, new_value, replacement_type)
            """
            if hitler_poi_entry is None:
                return False, None, None
            
            # Determine the reference price and swing type based on target_type
            if target_type == "exit":
                ref_price = exit_price
                # For exit, we need to infer the swing type from the order context
                # If it's a sell order, exit is below entry (like a swing low)
                # If it's a buy order, exit is above entry (like a swing high)
                if "sell" in order_type.lower():
                    ref_type = "swing_low"
                else:
                    ref_type = "swing_high"
            else:  # entry
                ref_price = entry_price
                # For entry, infer swing type from order type
                if "sell" in order_type.lower():
                    ref_type = "swing_high"  # Sell limit at high
                else:
                    ref_type = "swing_low"   # Buy limit at low
            
            if ref_price is None:
                return False, None, None
            
            # Apply the same condition logic as in apply_definitions_condition
            if mode == "behind":
                if ref_type == "swing_high":
                    # Behind a swing high means hitler_poi_entry should be below it
                    condition_met = hitler_poi_entry < ref_price
                elif ref_type == "swing_low":
                    # Behind a swing low means hitler_poi_entry should be above it
                    condition_met = hitler_poi_entry > ref_price
                else:
                    condition_met = False
            else:  # beyond
                if ref_type == "swing_high":
                    # Beyond a swing high means hitler_poi_entry should be above it
                    condition_met = hitler_poi_entry > ref_price
                elif ref_type == "swing_low":
                    # Beyond a swing low means hitler_poi_entry should be below it
                    condition_met = hitler_poi_entry < ref_price
                else:
                    condition_met = False
            
            if condition_met:
                return True, hitler_poi_entry, target_type
            else:
                return False, None, None
        
        # =================================================================
        # PROCESS LIMIT_ORDERS.JSON
        # =================================================================
        if os.path.exists(limit_orders_file):
            try:
                with open(limit_orders_file, 'r', encoding='utf-8') as f:
                    limit_orders = json.load(f)
            except Exception:
                limit_orders = []
            
            if limit_orders and isinstance(limit_orders, list):
                orders_modified = False
                
                for idx, order in enumerate(limit_orders):
                    # Extract order data
                    order_type = order.get("order_type", "")
                    entry_price = order.get("entry", 0)
                    exit_price = order.get("exit", 0)
                    target_price = order.get("target", 0)
                    hitler_poi_entry = order.get("hitler_poi_entry")
                    hit_from_above = order.get("hit_from_above", False)
                    hit_from_below = order.get("hit_from_below", False)
                    
                    # Skip if hitler_poi_entry is missing
                    if hitler_poi_entry is None:
                        continue
                    
                    # Check condition and determine if replacement is needed
                    should_replace, new_value, replacement_type = check_condition_and_replace(
                        order, order_type, entry_price, exit_price, target_price,
                        hitler_poi_entry, hit_from_above, hit_from_below
                    )
                    
                    if should_replace:
                        # Store original value for logging/tracking
                        original_value = order.get(replacement_type, 0)
                        
                        # Replace the target price
                        order[replacement_type] = new_value
                        order[f"{replacement_type}_replaced_by_hitler_poi_entry"] = True
                        order[f"{replacement_type}_original_value"] = original_value
                        order[f"{replacement_type}_replacement_condition"] = condition_cfg
                        order[f"{replacement_type}_replacement_mode"] = mode
                        
                        # Also store the hitler_poi_entry that was used
                        order[f"{replacement_type}_replaced_with"] = new_value
                        
                        orders_modified = True
                        modified = True
                        
                        # Log the replacement
                        log(f"    🔄 Replaced {replacement_type} in limit order: {original_value:.5f} -> {new_value:.5f} (condition: {condition_cfg})")
                
                # Write back if modified
                if orders_modified:
                    with open(limit_orders_file, 'w', encoding='utf-8') as f:
                        json.dump(limit_orders, f, indent=4)
        
        # =================================================================
        # PROCESS POI_ENTRY.JSON
        # =================================================================
        if os.path.exists(poi_entry_file):
            try:
                with open(poi_entry_file, 'r', encoding='utf-8') as f:
                    poi_entries = json.load(f)
            except Exception:
                poi_entries = []
            
            if poi_entries and isinstance(poi_entries, list):
                entries_modified = False
                
                for idx, entry in enumerate(poi_entries):
                    # Extract order data
                    order_type = entry.get("order_type", "")
                    entry_price = entry.get("entry", 0)
                    exit_price = entry.get("exit", 0)
                    target_price = entry.get("target", 0)
                    hitler_poi_entry = entry.get("hitler_poi_entry")
                    hit_from_above = entry.get("hit_from_above", False)
                    hit_from_below = entry.get("hit_from_below", False)
                    
                    # Skip if hitler_poi_entry is missing
                    if hitler_poi_entry is None:
                        continue
                    
                    # Check condition and determine if replacement is needed
                    should_replace, new_value, replacement_type = check_condition_and_replace(
                        entry, order_type, entry_price, exit_price, target_price,
                        hitler_poi_entry, hit_from_above, hit_from_below
                    )
                    
                    if should_replace:
                        # Store original value for logging/tracking
                        original_value = entry.get(replacement_type, 0)
                        
                        # Replace the target price
                        entry[replacement_type] = new_value
                        entry[f"{replacement_type}_replaced_by_hitler_poi_entry"] = True
                        entry[f"{replacement_type}_original_value"] = original_value
                        entry[f"{replacement_type}_replacement_condition"] = condition_cfg
                        entry[f"{replacement_type}_replacement_mode"] = mode
                        
                        # Also store the hitler_poi_entry that was used
                        entry[f"{replacement_type}_replaced_with"] = new_value
                        
                        entries_modified = True
                        modified = True
                        
                        # Log the replacement
                        log(f"    🔄 Replaced {replacement_type} in POI entry: {original_value:.5f} -> {new_value:.5f} (condition: {condition_cfg})")
                
                # Write back if modified
                if entries_modified:
                    with open(poi_entry_file, 'w', encoding='utf-8') as f:
                        json.dump(poi_entries, f, indent=4)
        
        return modified

    def limit_orders_old_record_cleanup(dev_base_path, new_folder_name):
        """
        Deletes the limit_orders.json file inside the specific new_filename folder 
        to ensure a fresh start for that entry's synchronization.
        """
        orders_file = os.path.join(dev_base_path, new_folder_name, "pending_orders", "limit_orders.json")
        if os.path.exists(orders_file):
            try:
                os.remove(orders_file)
            except Exception as e:
                log(f"Could not clear limit orders for {new_folder_name}: {e}")

    def identify_paused_symbols(target_data, dev_base_path, new_folder_name):
        """
        Synchronizes all limit orders with their pattern anchors (from/after) 
        and saves them to paused_symbols.json without overwriting previous symbols.
        """
        orders_file = os.path.join(dev_base_path, new_folder_name, "pending_orders", "limit_orders.json")
        paused_folder = os.path.join(dev_base_path, new_folder_name, "paused_symbols_folder")
        paused_file = os.path.join(paused_folder, "paused_symbols.json")

        if not os.path.exists(orders_file):
            return

        try:
            with open(orders_file, 'r', encoding='utf-8') as f:
                active_orders = json.load(f)
        except Exception as e:
            log(f"Error reading limit orders: {e}")
            return

        # Load existing paused records to append to them, or start fresh if it's the first symbol
        all_paused_records = []
        if os.path.exists(paused_file):
            try:
                with open(paused_file, 'r', encoding='utf-8') as f:
                    all_paused_records = json.load(f)
            except:
                all_paused_records = []

        # Create a lookup set of (symbol, timeframe, time) to avoid duplicate entries in paused_symbols
        existing_keys = {(r.get("symbol"), r.get("timeframe"), r.get("time")) for r in all_paused_records}

        new_records_found = False

        for order in active_orders:
            order_sym = order.get("symbol")
            order_tf = order.get("timeframe")
            order_entry = order.get("entry")
            
            # Access the specific timeframe data
            tf_data = target_data.get(order_tf, {})
            
            for key, value in tf_data.items():
                if key.endswith("_patterns"):
                    for p_name, family in value.items():
                        from_c = next((c for c in family if c.get("from") is True), None)
                        after_c = next((c for c in family if c.get("after") is True), None)

                        # MATCHING LOGIC: 
                        # 1. Symbol matches
                        # 2. This specific "from" candle hasn't been added yet
                        if from_c and after_c and from_c.get("symbol") == order_sym:
                            # We use time as a unique identifier for the pattern start
                            pattern_time = from_c.get("time")
                            
                            if (order_sym, order_tf, pattern_time) not in existing_keys:
                                # Create record with full order details
                                record = {
                                    "from": True,
                                    "symbol": order_sym,
                                    "timeframe": order_tf,
                                    "entry": order_entry,
                                    "order_type": order.get("order_type"),
                                    "time": pattern_time,
                                    "exit": order.get("exit", 0),
                                    "target": order.get("target"),
                                    "tick_size": order.get("tick_size"),
                                    "tick_value": order.get("tick_value"),
                                    "after": {
                                        "after": True,
                                        "time": after_c.get("time")
                                    }
                                }
                                all_paused_records.append(record)
                                existing_keys.add((order_sym, order_tf, pattern_time))
                                new_records_found = True

        # Save the cumulative list back to the file
        if new_records_found:
            os.makedirs(paused_folder, exist_ok=True)
            with open(paused_file, 'w', encoding='utf-8') as f:
                json.dump(all_paused_records, f, indent=4)
    
    def populate_limit_orders_with_paused_orders(dev_base_path, new_folder_name):
        """
        Checks the limit orders file and adds any orders from paused_symbols.json 
        that are missing in the active limit orders.
        
        Args:
            dev_base_path: Base development path
            new_folder_name: Current run folder name
        """
        orders_file = os.path.join(dev_base_path, new_folder_name, "pending_orders", "limit_orders.json")
        paused_folder = os.path.join(dev_base_path, new_folder_name, "paused_symbols_folder")
        paused_file = os.path.join(paused_folder, "paused_symbols.json")
        
        # If no paused symbols file exists, nothing to do
        if not os.path.exists(paused_file):
            return 0
        
        # Load paused symbols/orders
        try:
            with open(paused_file, 'r', encoding='utf-8') as f:
                paused_orders = json.load(f)
        except Exception as e:
            log(f"Error reading paused symbols file: {e}")
            return 0
        
        if not paused_orders:
            return 0
        
        # Load existing active limit orders, or create empty list if file doesn't exist
        active_orders = []
        if os.path.exists(orders_file):
            try:
                with open(orders_file, 'r', encoding='utf-8') as f:
                    active_orders = json.load(f)
            except Exception as e:
                log(f"Error reading limit orders file: {e}")
                active_orders = []
        
        # Create lookup set of existing active orders to identify missing ones
        # Using (symbol, timeframe, entry, time) as unique identifier
        existing_order_keys = set()
        for order in active_orders:
            key = (
                order.get("symbol"),
                order.get("timeframe"),
                order.get("entry"),
                order.get("time")  # pattern time
            )
            existing_order_keys.add(key)
        
        # Track orders to add
        orders_added = 0
        orders_to_add = []
        
        # Check each paused order and add if missing from active orders
        for paused_order in paused_orders:
            # Extract the after time from the nested structure
            after_time = None
            if "after" in paused_order and isinstance(paused_order["after"], dict):
                after_time = paused_order["after"].get("time")
            
            order_key = (
                paused_order.get("symbol"),
                paused_order.get("timeframe"),
                paused_order.get("entry"),
                paused_order.get("time")  # pattern time
            )
            
            # If this order is not in active orders, add it
            if order_key not in existing_order_keys:
                # Create a clean order object from the paused record
                new_order = {
                    "symbol": paused_order.get("symbol"),
                    "timeframe": paused_order.get("timeframe"),
                    "entry": paused_order.get("entry"),
                    "exit": paused_order.get("exit", 0),
                    "order_type": paused_order.get("order_type", "LIMIT"),
                    "target": paused_order.get("target"),
                    "tick_size": paused_order.get("tick_size"),
                    "tick_value": paused_order.get("tick_value"),
                    "time": paused_order.get("time"),  # pattern time
                    "from_paused": True,  # Flag to indicate this was restored from paused
                    "status": "active"
                }
                
                # Add after time if it exists
                if after_time:
                    new_order["after_time"] = after_time
                
                orders_to_add.append(new_order)
                existing_order_keys.add(order_key)  # Prevent duplicates in this run
                orders_added += 1
        
        # If we found missing orders, append them to the active orders and save
        if orders_added > 0:
            # Combine existing orders with new ones
            updated_orders = active_orders + orders_to_add
            
            # Ensure the pending_orders directory exists
            orders_dir = os.path.join(dev_base_path, new_folder_name, "pending_orders")
            os.makedirs(orders_dir, exist_ok=True)
            
            # Save the updated orders file
            try:
                with open(orders_file, 'w', encoding='utf-8') as f:
                    json.dump(updated_orders, f, indent=4)
            except Exception as e:
                log(f"Error writing updated limit orders: {e}")
                return 0
        
        return orders_added           

    def extract_poi_to_confirmation(target_data_tf, new_key, dev_base_path, new_folder_name, sym, pending_full_candle_refs, poi_confirmation_timeframes=None):
        """
        Extracts candles from point_of_interest markers and looks for the same timestamp in lower timeframes' full candle data.
        Creates {lower_tf}_confirmation_from_{source_tf}_poi_{original_key} structures in config.json
        
        ONLY creates confirmations for timeframe relationships explicitly defined in poi_confirmation_timeframes.
        No default relationships are created.
        
        Args:
            target_data_tf: The timeframe data in target_data
            new_key: The processed key (e.g., "supply_demand_buy_entries_supply_demand")
            dev_base_path: Base path to developers folder
            new_folder_name: The entry folder name
            sym: Symbol being processed
            pending_full_candle_refs: Dictionary of references to full candle data in config.json
            poi_confirmation_timeframes: Dictionary defining allowed POI -> confirmation timeframe relationships
                                        Format: {"source_tf": ["confirmation_tf1", "confirmation_tf2", ...]}
                                        If None or empty, NO confirmations will be created.
        """
        # -----------------------------------------------------------------
        # STRICT VALIDATION: Only proceed if we have confirmation timeframes configured
        # -----------------------------------------------------------------
        if not poi_confirmation_timeframes:
            # No configuration provided - don't create any confirmations
            return target_data_tf
        
        pattern_key = f"{new_key}_patterns"
        patterns = target_data_tf.get(pattern_key, {})
        
        if not patterns:
            return target_data_tf
        
        # Get the source timeframe from any POI candle
        source_tf = None
        for pattern_name, pattern_candles in patterns.items():
            if pattern_candles and len(pattern_candles) > 0:
                source_tf = pattern_candles[0].get("timeframe")
                if source_tf:
                    break
        
        if not source_tf:
            return target_data_tf
        
        # -----------------------------------------------------------------
        # STRICT FILTERING: Only use confirmation timeframes explicitly defined for this source_tf
        # -----------------------------------------------------------------
        # Check if this source timeframe has any configured confirmation relationships
        if source_tf not in poi_confirmation_timeframes:
            # No configuration for this source timeframe - skip completely
            return target_data_tf
        
        # Get the allowed confirmation timeframes for this source_tf
        allowed_confirmation_tfs = poi_confirmation_timeframes[source_tf]
        
        if not allowed_confirmation_tfs:
            # Empty list means no confirmations for this source_tf
            log(f"    ⏭️ Empty confirmation list for {source_tf} POI - skipping confirmations")
            return target_data_tf
        
        
        # Find all available timeframes from pending_full_candle_refs
        available_tfs = set()
        tf_to_ref_map = {}  # Map timeframe to its reference data
        for ref_key, ref_data in pending_full_candle_refs.items():
            if ref_key.startswith('full_candles_ref_') or '_full_candles_ref_' in ref_key:
                tf = ref_data["tf"]
                available_tfs.add(tf)
                tf_to_ref_map[tf] = ref_data
        
        # Filter allowed confirmation timeframes to only those that are available
        lower_tfs = []
        for tf in allowed_confirmation_tfs:
            if tf in available_tfs:
                lower_tfs.append(tf)
        
        if not lower_tfs:
            return target_data_tf
        
        # Collect all POI timestamps from source timeframe
        poi_timestamps = set()
        poi_candles = []  # Store the actual POI candles for reference
        
        for pattern_name, pattern_candles in patterns.items():
            for candle in pattern_candles:
                if candle.get("point_of_interest") is True:
                    timestamp = candle.get("time")
                    if timestamp:
                        poi_timestamps.add(timestamp)
                        poi_candles.append(candle)
        
        if not poi_timestamps:
            return target_data_tf
        
        log(f"  🔍 Found {len(poi_timestamps)} POI candles in {source_tf} for {sym}")
        
        any_confirmations_created = False
        
        # For each POI timestamp, look for it in each allowed lower timeframe
        for timestamp in sorted(list(poi_timestamps)):
            
            # Find matching POI candle for metadata
            source_poi_candle = next((p for p in poi_candles if p.get("time") == timestamp), None)
            
            # For each lower timeframe, try to find the candle
            for lower_tf in lower_tfs:
                # Get the reference data for this timeframe
                ref_data = tf_to_ref_map.get(lower_tf)
                if not ref_data:
                    continue
                    
                # The candles are stored in target_data_tf under the config_key
                lower_tf_candles = ref_data["target_data_ref"].get(ref_data["config_key"], [])
                
                if not lower_tf_candles:
                    log(f"      ⚠️ No candle data found for {lower_tf}")
                    continue
                
                # Find the index of this timestamp in lower timeframe candles
                poi_index = -1
                for i, candle in enumerate(lower_tf_candles):
                    if candle.get("time") == timestamp:
                        poi_index = i
                        break
                
                if poi_index == -1:
                    #log(f"      ⚠️ Timestamp {timestamp} not found in {lower_tf}")
                    continue
                
                any_confirmations_created = True
                
                # Extract from this index to the end (latest)
                candles_from_poi = lower_tf_candles[poi_index:]
                
                # Mark which POI these candles belong to
                for candle in candles_from_poi:
                    candle["poi_origin_time"] = timestamp
                    candle["poi_origin_tf"] = source_tf
                    if source_poi_candle:
                        candle["poi_origin_pattern"] = source_poi_candle.get("swing_type", "unknown")
                        # Copy important POI attributes
                        for attr in ["point_of_interest", "swing_type", "swing_high", "swing_low"]:
                            if attr in source_poi_candle:
                                candle[f"source_poi_{attr}"] = source_poi_candle.get(attr)
                
                # Create the confirmation key in the format: {lower_tf}_confirmation_from_{source_tf}_poi_{original_key}
                # Remove the new_folder_name prefix from new_key to get original
                original_key = new_key.replace(f"{new_folder_name}_", "", 1) if new_key.startswith(f"{new_folder_name}_") else new_key
                confirmation_key = f"{lower_tf}_confirmation_from_{source_tf}_poi_{original_key}"
                
                # Add or append to existing data for this confirmation key
                if confirmation_key not in target_data_tf:
                    target_data_tf[confirmation_key] = []
                
                # Add unique candles (avoid duplicates)
                existing_times = {c.get("time") for c in target_data_tf[confirmation_key]}
                new_candles = [c for c in candles_from_poi if c.get("time") not in existing_times]
                target_data_tf[confirmation_key].extend(new_candles)
                
                # Sort by time
                target_data_tf[confirmation_key].sort(key=lambda x: x.get("time", ""))
        
        return target_data_tf

    def generate_confirmation_charts(dev_base_path, new_folder_name, sym, target_sym_dir, target_data, pending_full_candle_data, tfs_to_keep=None):
        """
        Generates brand new charts for confirmation data extracted from POI candles.
        Creates charts directly from the confirmation candle data without needing source charts.
        Features dynamic width scaling for optimal candle visibility.
        Records pixel coordinates for each candle in the target_data structure.
        Labels swing candles with their numbers above (for higher highs) or below (for lower lows).
        
        Chart filename format: {lower_tf}_confirmation_from_{source_tf}_poi.png
        
        Args:
            dev_base_path: Base path to developers folder
            new_folder_name: The entry folder name
            sym: Symbol being processed
            target_sym_dir: Target symbol directory
            target_data: The complete target data dictionary (all timeframes)
            pending_full_candle_data: Dictionary of queued full candle data for ALL timeframes
            tfs_to_keep: Optional list of timeframes to process
        """
        # Determine which timeframes to process
        if tfs_to_keep is None:
            timeframes_to_process = list(target_data.keys())
        else:
            timeframes_to_process = tfs_to_keep
        
        chart_count = 0
        
        # Configuration for readable candles
        MIN_CANDLE_WIDTH = 30  # Minimum pixels per candle for readability
        MAX_CANDLE_WIDTH = 40  # Maximum pixels per candle (prevents extremely wide images)
        MIN_CANDLE_SPACING = 20  # Minimum pixels between candles
        BASE_HEIGHT = 4000  # Fixed height for all charts
        MAX_IMAGE_WIDTH = 90000000  # Maximum width to prevent insane image sizes
        
        # Border and padding configuration
        BORDER_THICKNESS = 1  # Thickness of the border line
        
        # OUTER PADDING (image edge to border)
        OUTER_PADDING_LEFT = 10
        OUTER_PADDING_RIGHT = 10
        OUTER_PADDING_TOP = 70
        OUTER_PADDING_BOTTOM = 70
        
        # INNER PADDING (border to chart area)
        INNER_PADDING_LEFT = 40      # Space from left border to first candle
        INNER_PADDING_RIGHT = 500     # Space from right border to last candle
        INNER_PADDING_TOP = 20       # Space from top border to highest candle
        INNER_PADDING_BOTTOM = 20    # Space from bottom border to lowest candle
        
        # Numbering configuration for swing candles only
        SWING_NUMBER_FONT_SCALE = 1  # Font size for swing candle numbers
        SWING_NUMBER_FONT_THICKNESS = 2
        SWING_NUMBER_OFFSET = 25  # Pixels away from wick to place the number
        SWING_NUMBER_BG_PADDING = 5  # Padding around number for background
        
        # Process each timeframe
        for tf in timeframes_to_process:
            if tf not in target_data:
                continue
                
            target_data_tf = target_data[tf]
            
            # Find all confirmation keys in this timeframe's data
            # New format: {lower_tf}_confirmation_from_{source_tf}_poi_{original_key}
            confirmation_keys = [key for key in target_data_tf.keys() if "_confirmation_from_" in key]
            
            for conf_key in confirmation_keys:
                # Parse the confirmation key to get source and target timeframes
                # Format: {lower_tf}_confirmation_from_{source_tf}_poi_{original_key}
                parts = conf_key.split('_confirmation_from_')
                
                if len(parts) != 2:
                    continue
                    
                target_tf = parts[0]  # This is the lower timeframe
                remaining = parts[1]
                
                # Split remaining into source_tf and original_key
                source_parts = remaining.split('_', 1)
                if len(source_parts) != 2:
                    continue
                    
                source_tf = source_parts[0]
                original_key = source_parts[1]
                
                if not source_tf or not target_tf:
                    continue
                
                # Get the confirmation data
                confirmation_data = target_data_tf.get(conf_key, [])
                if not confirmation_data:
                    continue
                
                # Extract OHLC data from confirmation candles, preserving candle_number and swing info
                ohlc_data = []
                for item in confirmation_data:
                    # FIX: Check if item is a dictionary or a string
                    if isinstance(item, dict):
                        # It's a candle dictionary - proceed normally
                        candle_dict = {
                            'time': item.get('time', ''),
                            'open': item.get('open', 0),
                            'high': item.get('high', 0),
                            'low': item.get('low', 0),
                            'close': item.get('close', 0),
                            'candle_number': item.get('candle_number', None),  # Preserve the original candle number
                            'is_swing': item.get('is_swing', False),  # Check if it's a swing candle
                            'swing_type': item.get('swing_type', None),  # Type of swing (swing_high, swing_low, etc.)
                            'original_candle': item  # Store reference to original candle for updating coordinates
                        }
                        ohlc_data.append(candle_dict)
                    elif isinstance(item, str):
                        # It's a string (possibly just a timestamp) - create a minimal candle
                        timestamp = item
                        log(f"       ⚠️ Warning: Found string instead of candle dict in {conf_key}: {timestamp[:50] if len(timestamp) > 50 else timestamp}")
                        
                        # Create a placeholder candle with just the timestamp
                        ohlc_data.append({
                            'time': timestamp,
                            'open': 0,
                            'high': 0,
                            'low': 0,
                            'close': 0,
                            'candle_number': None,
                            'is_swing': False,
                            'swing_type': None,
                            'original_candle': {'time': timestamp}  # Create a minimal original candle
                        })
                    else:
                        # Unknown type - skip
                        log(f"       ⚠️ Warning: Unexpected data type in {conf_key}: {type(item)}")
                        continue
                
                if not ohlc_data:
                    continue
                
                num_candles = len(ohlc_data)
                
                # -----------------------------------------------------------------
                # DYNAMIC WIDTH CALCULATION
                # -----------------------------------------------------------------
                
                # Determine optimal candle width based on number of candles
                if num_candles <= 50:
                    # Few candles - make them larger for better visibility
                    base_candle_width = 15
                    base_spacing_multiplier = 1.8
                elif num_candles <= 200:
                    # Medium number of candles - moderate size
                    base_candle_width = 10
                    base_spacing_multiplier = 1.6
                elif num_candles <= 1000:
                    # Many candles - smaller but still readable
                    base_candle_width = 6
                    base_spacing_multiplier = 1.4
                else:
                    # Very many candles - minimum readable size
                    base_candle_width = MIN_CANDLE_WIDTH
                    base_spacing_multiplier = 1.3
                
                # Apply constraints to candle width
                target_candle_width = max(base_candle_width, MIN_CANDLE_WIDTH)
                target_candle_width = min(target_candle_width, MAX_CANDLE_WIDTH)
                
                # Calculate spacing based on candle width and multiplier
                desired_spacing = target_candle_width * base_spacing_multiplier
                
                # Apply minimum spacing constraint
                actual_spacing = max(desired_spacing, MIN_CANDLE_SPACING)
                
                # Calculate the total width needed for candles (from first candle center to last candle center)
                if num_candles > 1:
                    total_span = actual_spacing * (num_candles - 1)
                else:
                    total_span = target_candle_width * 2  # For single candle, give it some space
                
                # Calculate the total width needed for the chart area (including half candles at edges)
                chart_area_width = total_span + target_candle_width
                
                # Add inner padding to get the bordered area width
                bordered_area_width = chart_area_width + INNER_PADDING_LEFT + INNER_PADDING_RIGHT
                
                # Add outer padding to get total image width
                img_width = int(bordered_area_width + OUTER_PADDING_LEFT + OUTER_PADDING_RIGHT)
                
                # Cap width to prevent insane image sizes
                img_width = min(img_width, MAX_IMAGE_WIDTH)
                
                # If width is less than minimum, use minimum
                min_width = OUTER_PADDING_LEFT + OUTER_PADDING_RIGHT + 1000
                if img_width < min_width:
                    img_width = min_width
                
                # Create the dynamic-sized chart
                chart_img = np.ones((BASE_HEIGHT, img_width, 3), dtype=np.uint8) * 255
                
                # Calculate price range for scaling
                all_prices = []
                for d in ohlc_data:
                    # Only include prices if they're non-zero (placeholders might be zero)
                    if d['high'] > 0 or d['low'] > 0:
                        all_prices.extend([d['high'], d['low']])
                
                # If all prices are zero (all placeholder candles), create a dummy range
                if not all_prices:
                    all_prices = [0, 100]  # Dummy range for display
                    log(f"       ⚠️ Warning: No valid price data in {conf_key}, using dummy range")
                
                min_price = min(all_prices)
                max_price = max(all_prices)
                price_range = max_price - min_price
                
                # Add padding to price range (10% on top and bottom)
                price_padding = price_range * 0.1
                min_price -= price_padding
                max_price += price_padding
                price_range = max_price - min_price
                
                # Border positions using OUTER padding (image edge to border)
                border_left = OUTER_PADDING_LEFT
                border_right = img_width - OUTER_PADDING_RIGHT
                border_top = OUTER_PADDING_TOP
                border_bottom = BASE_HEIGHT - OUTER_PADDING_BOTTOM
                
                # Draw border around the chart area
                cv2.rectangle(chart_img, 
                            (border_left, border_top), 
                            (border_right, border_bottom), 
                            (0, 0, 0), BORDER_THICKNESS)
                
                # Chart area INSIDE the border using INNER padding (border to chart)
                chart_left = border_left + INNER_PADDING_LEFT
                chart_right = border_right - INNER_PADDING_RIGHT
                chart_top = border_top + INNER_PADDING_TOP
                chart_bottom = border_bottom - INNER_PADDING_BOTTOM
                chart_width = chart_right - chart_left
                chart_height = chart_bottom - chart_top
                
                # Calculate where to start drawing candles
                # We want to center the candles in the available chart area
                if num_candles > 1:
                    # Calculate if our pre-calculated spacing fits within the chart area
                    if total_span <= chart_width - target_candle_width:
                        # Candles fit - center them
                        start_x = chart_left + (chart_width - (total_span + target_candle_width)) / 2 + (target_candle_width / 2)
                    else:
                        # Something went wrong with calculations - fallback to left alignment
                        start_x = chart_left + (target_candle_width / 2)
                        log(f"       ⚠️ Warning: Spacing calculation mismatch - using fallback")
                else:
                    # Single candle - center it
                    start_x = chart_left + (chart_width / 2)
                
                # Define price to y conversion function for reuse
                def price_to_y(price):
                    # Handle case where price_range is zero to avoid division by zero
                    if price_range == 0:
                        return chart_bottom - chart_height // 2
                    return chart_bottom - int((price - min_price) / price_range * chart_height)
                
                # Draw each candle and record coordinates
                for i, candle in enumerate(ohlc_data):
                    # Calculate x position
                    if num_candles > 1:
                        x_center = start_x + (i * actual_spacing)
                    else:
                        x_center = start_x
                    
                    # Determine if bullish or bearish (for placeholder candles, treat as neutral/gray)
                    if candle['close'] == 0 and candle['open'] == 0:
                        # Placeholder candle - use gray
                        color = (128, 128, 128)
                        is_bullish = None
                    else:
                        is_bullish = candle['close'] >= candle['open']
                        # Use default green for bullish, red for bearish
                        color = (0, 150, 0) if is_bullish else (0, 0, 255)
                    
                    # Calculate y positions for all OHLC values
                    open_y = price_to_y(candle['open'])
                    close_y = price_to_y(candle['close'])
                    high_y = price_to_y(candle['high'])
                    low_y = price_to_y(candle['low'])
                    
                    # Calculate candle rectangle coordinates for the body
                    half_width = target_candle_width / 2
                    candle_left_x = int(x_center - half_width)
                    candle_right_x = int(x_center + half_width)
                    
                    # For the body: top is min(open, close), bottom is max(open, close)
                    body_top_y = min(open_y, close_y)
                    body_bottom_y = max(open_y, close_y)
                    
                    # Draw the wick (high-low line) - only if we have valid price data
                    if candle['high'] != 0 or candle['low'] != 0:
                        cv2.line(chart_img, 
                                (int(x_center), high_y), 
                                (int(x_center), low_y), 
                                color, 1)
                    
                    # Draw the candle body - only if we have valid open/close
                    if candle['open'] != 0 or candle['close'] != 0:
                        cv2.rectangle(chart_img,
                                    (candle_left_x, body_top_y),
                                    (candle_right_x, body_bottom_y),
                                    color, -1)
                    
                    # -----------------------------------------------------------------
                    # LABEL SWING CANDLES ONLY WITH THEIR NUMBERS
                    # -----------------------------------------------------------------
                    if candle.get('is_swing', False):
                        # Get the actual candle number
                        candle_number = candle.get('candle_number')
                        
                        if candle_number is not None:
                            number_text = str(candle_number)
                            
                            # Calculate text size for background
                            (text_width, text_height), baseline = cv2.getTextSize(
                                number_text, cv2.FONT_HERSHEY_SIMPLEX, SWING_NUMBER_FONT_SCALE, SWING_NUMBER_FONT_THICKNESS
                            )
                            
                            # Determine position based on swing type
                            swing_type = candle.get('swing_type', '')
                            
                            if swing_type == 'swing_high':
                                # Position number ABOVE the wick
                                number_x = int(x_center - text_width / 2)
                                number_y = high_y - SWING_NUMBER_OFFSET
                                
                                # Draw arrow pointing up (optional)
                                arrow_start = (int(x_center), high_y - 5)
                                arrow_end = (int(x_center), number_y + text_height + 5)
                                cv2.arrowedLine(chart_img, arrow_start, arrow_end, (0, 0, 255), 1, tipLength=0.3)
                                
                            elif swing_type == 'swing_low':
                                # Position number BELOW the wick
                                number_x = int(x_center - text_width / 2)
                                number_y = low_y + SWING_NUMBER_OFFSET + text_height
                                
                                # Draw arrow pointing down (optional)
                                arrow_start = (int(x_center), low_y + 5)
                                arrow_end = (int(x_center), number_y - text_height - 5)
                                cv2.arrowedLine(chart_img, arrow_start, arrow_end, (0, 255, 0), 1, tipLength=0.3)
                                
                            else:
                                # For other swing types, default to above
                                number_x = int(x_center - text_width / 2)
                                number_y = high_y - SWING_NUMBER_OFFSET
                            
                            # Draw white background for better readability
                            bg_x1 = number_x - SWING_NUMBER_BG_PADDING
                            bg_y1 = number_y - text_height - SWING_NUMBER_BG_PADDING
                            bg_x2 = number_x + text_width + SWING_NUMBER_BG_PADDING
                            bg_y2 = number_y + SWING_NUMBER_BG_PADDING
                            
                            # Ensure background stays within image bounds
                            bg_x1 = max(0, bg_x1)
                            bg_y1 = max(0, bg_y1)
                            bg_x2 = min(img_width, bg_x2)
                            bg_y2 = min(BASE_HEIGHT, bg_y2)
                            
                            # Draw white rectangle background
                            cv2.rectangle(chart_img, (bg_x1, bg_y1), (bg_x2, bg_y2), (255, 255, 255), -1)
                            
                            # Draw black border around background for better visibility
                            cv2.rectangle(chart_img, (bg_x1, bg_y1), (bg_x2, bg_y2), (0, 0, 0), 1)
                            
                            # Draw the number in black
                            cv2.putText(chart_img, number_text, (number_x, number_y),
                                    cv2.FONT_HERSHEY_SIMPLEX, SWING_NUMBER_FONT_SCALE, (0, 0, 0), SWING_NUMBER_FONT_THICKNESS)
                            
                            # Also add small indicator text for swing type (optional)
                            type_text = "HH" if swing_type == 'swing_high' else "LL" if swing_type == 'swing_low' else ""
                            if type_text:
                                (type_width, type_height), _ = cv2.getTextSize(
                                    type_text, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1
                                )
                                type_x = int(x_center - type_width / 2)
                                if swing_type == 'swing_high':
                                    type_y = number_y - text_height - 5
                                else:
                                    type_y = number_y + 15
                                cv2.putText(chart_img, type_text, (type_x, type_y),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (100, 100, 100), 1)
                    
                    # -----------------------------------------------------------------
                    # RECORD CANDLE COORDINATES IN THE ORIGINAL DATA STRUCTURE
                    # -----------------------------------------------------------------
                    # Only try to record coordinates if we have a valid original_candle that's a dict
                    original_candle = candle.get('original_candle')
                    if original_candle and isinstance(original_candle, dict):
                        # Calculate full candle dimensions (including wick)
                        full_candle_height = abs(low_y - high_y)
                        body_height = abs(body_bottom_y - body_top_y)
                        
                        # Record position data for the FULL candle (including wick)
                        original_candle['candle_x'] = int(x_center)  # Center x-coordinate
                        original_candle['candle_y'] = high_y  # Top of wick (highest point)
                        original_candle['candle_width'] = candle_right_x - candle_left_x  # Body width
                        original_candle['candle_height'] = full_candle_height  # Full height including wick
                        original_candle['candle_left'] = candle_left_x
                        original_candle['candle_right'] = candle_right_x
                        original_candle['candle_top'] = high_y  # Top of wick
                        original_candle['candle_bottom'] = low_y  # Bottom of wick
                        
                        # Record body-specific coordinates
                        original_candle['body_top'] = body_top_y
                        original_candle['body_bottom'] = body_bottom_y
                        original_candle['body_height'] = body_height
                        
                        # Record wick coordinates
                        original_candle['wick_top'] = high_y
                        original_candle['wick_bottom'] = low_y
                        original_candle['wick_x'] = int(x_center)
                        
                        # Also record drawing coordinates (matching the full candle)
                        original_candle['draw_x'] = int(x_center)
                        original_candle['draw_y'] = high_y
                        original_candle['draw_w'] = candle_right_x - candle_left_x
                        original_candle['draw_h'] = full_candle_height
                        original_candle['draw_left'] = candle_left_x
                        original_candle['draw_right'] = candle_right_x
                        original_candle['draw_top'] = high_y
                        original_candle['draw_bottom'] = low_y
                        
                        # Record individual OHLC pixel positions
                        original_candle['open_pixel_y'] = open_y
                        original_candle['high_pixel_y'] = high_y
                        original_candle['low_pixel_y'] = low_y
                        original_candle['close_pixel_y'] = close_y
                        
                        # Add chart metadata
                        original_candle['chart_width'] = img_width
                        original_candle['chart_height'] = BASE_HEIGHT
                        original_candle['chart_timeframe'] = target_tf
                        original_candle['source_timeframe'] = source_tf
                        original_candle['confirmation_key'] = conf_key
                        
                        # Add price range metadata for scaling reference
                        original_candle['chart_min_price'] = min_price
                        original_candle['chart_max_price'] = max_price
                        original_candle['chart_price_range'] = price_range
                
                # Add title with candle count info - CHART NAME FORMAT: {target_tf}_confirmation_from_{source_tf}_poi
                title = f"{sym} {target_tf}_confirmation_from_{source_tf}_poi ({num_candles} candles)"
                
                # Calculate text size to center it
                text_size = cv2.getTextSize(title, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)[0]
                text_x = (img_width - text_size[0]) // 2
                text_y = OUTER_PADDING_TOP // 2
                
                cv2.putText(chart_img, title, (text_x, text_y), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)
                
                # Add detailed info for debugging/verification
                swing_count = sum(1 for c in ohlc_data if c.get('is_swing', False))
                info_text = f"Width:{target_candle_width}px Spacing:{actual_spacing:.1f}px | Swing candles: {swing_count} | Img Width:{img_width}px"
                cv2.putText(chart_img, info_text, (OUTER_PADDING_LEFT, BASE_HEIGHT - 10), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (100, 100, 100), 1)
                
                # Save the confirmation chart - FILENAME FORMAT: {target_tf}_confirmation_from_{source_tf}_poi.png
                output_filename = f"{target_tf}_confirmation_from_{source_tf}_poi.png"
                output_path = os.path.join(target_sym_dir, output_filename)
                cv2.imwrite(output_path, chart_img)
                
                chart_count += 1
        
        if chart_count > 0:
            log(f"  📊 Generated {chart_count} confirmation charts for {sym}")

    def move_confirmation_keys_to_target_timeframes(target_data, dev_base_path, new_folder_name, sym):
        """
        Helper function to reorganize confirmation keys to their target timeframes.
        
        Args:
            target_data: The target_data dictionary containing all timeframe data
            dev_base_path: Base development path
            new_folder_name: New folder name for the entry
            sym: Current symbol being processed
        
        Returns:
            bool: True if any modifications were made, False otherwise
        """
        modified = False
        
        # First, collect all confirmation keys from all timeframes
        confirmation_keys_to_move = []
        for source_tf, tf_data in list(target_data.items()):
            if isinstance(tf_data, dict):
                for key in list(tf_data.keys()):
                    # Check if this is a confirmation key (contains "_confirmation_from_")
                    if "_confirmation_from_" in key:
                        # Parse the key to get the target timeframe
                        # Format: {target_tf}_confirmation_from_{source_tf}_poi_{original_key}
                        parts = key.split('_confirmation_from_')
                        if len(parts) == 2:
                            target_tf = parts[0]  # This is the timeframe where it should belong
                            confirmation_keys_to_move.append({
                                'source_tf': source_tf,
                                'target_tf': target_tf,
                                'key': key,
                                'data': tf_data[key]
                            })
        
        # Now move each confirmation key to its target timeframe
        for item in confirmation_keys_to_move:
            source_tf = item['source_tf']
            target_tf = item['target_tf']
            key = item['key']
            data = item['data']
            
            # Skip if source and target are the same (already in correct place)
            if source_tf == target_tf:
                continue
            
            # Ensure target timeframe exists in target_data
            if target_tf not in target_data:
                target_data[target_tf] = {}
            
            # Check if this key already exists in target timeframe
            if key not in target_data[target_tf]:
                # Move the data to target timeframe
                target_data[target_tf][key] = data
                
                # Remove from source timeframe
                if key in target_data[source_tf]:
                    del target_data[source_tf][key]
                    modified = True
                    
                    # If source timeframe becomes empty after removal, we could optionally remove it
                    # But we'll leave that for cleanup elsewhere
            else:
                # Key already exists in target - we need to merge
                log(f"  ⚠️ Key {key} already exists in {target_tf}, merging data")
                
                # Get existing data
                existing_data = target_data[target_tf][key]
                
                # Create a set of existing timestamps to avoid duplicates
                existing_timestamps = set()
                for candle in existing_data:
                    if 'time' in candle:
                        existing_timestamps.add(candle['time'])
                
                # Add new candles that don't already exist
                new_candles_added = 0
                for candle in data:
                    if 'time' in candle and candle['time'] not in existing_timestamps:
                        existing_data.append(candle)
                        new_candles_added += 1
                
                if new_candles_added > 0:
                    # Sort by time
                    existing_data.sort(key=lambda x: x.get('time', ''))
                    modified = True
                    log(f"    ✅ Added {new_candles_added} new candles to existing data")
                
                # Remove from source timeframe
                if key in target_data[source_tf]:
                    del target_data[source_tf][key]
                    modified = True
        
        return modified
    
    def populate_other_timeframes_with_confirmation_entry(target_data, dev_base_path, new_folder_name, sym):
        """
        Populate original candle lists with confirmation data from their corresponding confirmation keys.
        This overwrites the original candle data with the confirmation data, completely replacing it.
        Creates a backup of the original data under a 'backup' key before overwriting.
        
        Args:
            target_data: The target_data dictionary containing all timeframe data
            dev_base_path: Base development path
            new_folder_name: New folder name for the entry
            sym: Current symbol being processed
        
        Returns:
            bool: True if any modifications were made, False otherwise
        """
        modified = False
        
        # First, collect all confirmation keys and map them to their target candle lists
        # Format: {target_tf}_confirmation_from_{source_tf}_poi_{original_key}
        # We need to map this to: original_key (without the prefix) in the target_tf
        
        for tf, tf_data in target_data.items():
            if not isinstance(tf_data, dict):
                continue
                
            # Find all confirmation keys in this timeframe
            confirmation_keys = []
            for key in list(tf_data.keys()):
                if "_confirmation_from_" in key:
                    # Parse the key to understand what it's confirming
                    # Format: {target_tf}_confirmation_from_{source_tf}_poi_{original_key}
                    parts = key.split('_confirmation_from_')
                    if len(parts) == 2:
                        target_tf = parts[0]  # The timeframe this confirmation belongs to
                        remainder = parts[1]
                        
                        # Further split to get source_tf and original_key
                        # remainder format: {source_tf}_poi_{original_key}
                        source_parts = remainder.split('_poi_')
                        if len(source_parts) == 2:
                            source_tf = source_parts[0]
                            original_key = source_parts[1]
                            
                            confirmation_keys.append({
                                'timeframe': tf,
                                'key': key,
                                'data': tf_data[key],
                                'target_tf': target_tf,
                                'source_tf': source_tf,
                                'original_key': original_key
                            })
            
            # Now process each confirmation key to populate its target candle lists
            for conf_item in confirmation_keys:
                conf_tf = conf_item['timeframe']
                conf_key = conf_item['key']
                conf_data = conf_item['data']
                target_tf = conf_item['target_tf']
                source_tf = conf_item['source_tf']
                original_key = conf_item['original_key']
                
                # We want to populate candle lists in the target_tf (where the confirmation belongs)
                # Look for candle lists in target_tf that match patterns related to the original_key
                
                if target_tf in target_data and isinstance(target_data[target_tf], dict):
                    target_tf_data = target_data[target_tf]
                    
                    # Find all candle lists in this timeframe that should be updated
                    # These would be keys that contain the original_key or are the original_key itself
                    candle_lists_to_update = []
                    
                    for candle_key in list(target_tf_data.keys()):
                        # Skip if this is a patterns key or a confirmation key
                        if candle_key.endswith('_patterns') or '_confirmation_from_' in candle_key:
                            continue
                        
                        # Check if this candle list should be updated with confirmation data
                        # It should be updated if it's related to the original_key
                        # This includes:
                        # 1. Exact match with original_key
                        # 2. Keys that contain original_key as a suffix (like "PREFIX_original_key")
                        # 3. Keys that are the base name without the new_folder_name prefix
                        
                        candle_key_lower = candle_key.lower()
                        original_key_lower = original_key.lower()
                        
                        # Check for various matching patterns
                        should_update = (
                            candle_key == original_key or  # Exact match
                            candle_key.endswith(f"_{original_key}") or  # Suffix match
                            candle_key_lower.endswith(f"_{original_key_lower}") or  # Case insensitive suffix
                            original_key_lower in candle_key_lower or  # Contains the original key
                            candle_key.replace(f"{new_folder_name}_", "") == original_key  # Without prefix
                        )
                        
                        if should_update:
                            candle_lists_to_update.append(candle_key)
                    
                    # Also check for keys that might be the base pattern name
                    # For example, if original_key is "swing_points", also look for 
                    # "STRUCTURAL-LIQUIDITY_swing_points" and similar
                    for candle_key in list(target_tf_data.keys()):
                        if candle_key.endswith('_patterns') or '_confirmation_from_' in candle_key:
                            continue
                        
                        # If the candle_key contains the original_key as a suffix after an underscore
                        parts = candle_key.split('_')
                        if len(parts) > 1 and parts[-1] == original_key:
                            if candle_key not in candle_lists_to_update:
                                candle_lists_to_update.append(candle_key)
                    
                    # Remove duplicates
                    candle_lists_to_update = list(set(candle_lists_to_update))
                    
                    # Now update each identified candle list with the confirmation data
                    if candle_lists_to_update:
                        
                        # Create backup of original data before overwriting
                        # We only need one backup since all candle lists being updated have the same data
                        # (they all correspond to the same original pattern)
                        
                        # Get the first candle list to backup (they all have the same data)
                        first_candle_key = candle_lists_to_update[0]
                        original_data = target_tf_data.get(first_candle_key, [])
                        
                        # Create backup key name based on the original_key
                        # Format: backup_original_key
                        backup_key = f"backup"
                        
                        # Only create backup if it doesn't already exist
                        if backup_key not in target_tf_data:
                            target_tf_data[backup_key] = original_data.copy()
                            modified = True
                        
                        # Now update all candle lists with confirmation data
                        for candle_key in candle_lists_to_update:
                            # COMPLETELY REPLACE the original data with confirmation data
                            # This is what the user requested: overwrite/remove original
                            target_tf_data[candle_key] = conf_data.copy()
                            modified = True
        
        return modified

    def filter_empty_symbol_folders(dev_base_path, folder_name):
        """
        Remove symbol folders that contain no files (empty directories).
        
        Args:
            dev_base_path: Base development path
            folder_name: Name of the folder containing symbol subfolders
            
        Returns:
            int: Number of empty folders deleted
        """
        folder_path = os.path.join(dev_base_path, folder_name)
        if not os.path.exists(folder_path):
            log(f"Folder {folder_path} does not exist, skipping empty folder filter")
            return 0
        
        deleted_count = 0
        
        # Iterate through all items in the folder
        for item_name in os.listdir(folder_path):
            item_path = os.path.join(folder_path, item_name)
            
            # Only process directories (symbol folders)
            if os.path.isdir(item_path):
                # Check if directory is empty (no files/subdirectories)
                if not os.listdir(item_path):
                    try:
                        shutil.rmtree(item_path)
                        deleted_count += 1
                    except Exception as e:
                        log(f"   Error deleting empty folder {item_name}: {e}")
        
        return deleted_count
    
    def swap_from_key_swing_type_values_to_target(target_data, dev_base_path, new_folder_name, sym, data_swapping_config):
        """
        Swaps swing_type values from a source key to a target key across all timeframes and confirmation data.
        
        Args:
            target_data: The target_data dictionary containing all timeframe data
            dev_base_path: Base development path
            new_folder_name: New folder name for the entry
            sym: Current symbol being processed
            data_swapping_config: Dictionary with 'from' and 'to' keys (e.g., {"from": "swing_points2", "to": "swing_points"})
        
        Returns:
            bool: True if any modifications were made, False otherwise
        """
        # Validate input
        if not data_swapping_config:
            log(f"  ⏭️ No data_swapping configuration for {sym}")
            return False
        
        from_key = data_swapping_config.get("from")
        to_key = data_swapping_config.get("to")
        
        if not from_key or not to_key:
            log(f"  ⏭️ Missing 'from' or 'to' key in data_swapping config for {sym}")
            return False
        
        log(f"\n  🔄 SWING TYPE SWAPPING for {sym}")
        log(f"     From: '{from_key}' → To: '{to_key}'")
        
        # Track modifications
        modified = False
        total_candles_updated = 0
        
        # First, identify all timeframes in target_data
        for tf, tf_data in list(target_data.items()):
            if not isinstance(tf_data, dict):
                continue
            
            # Look for all keys that contain the target 'to_key' (including confirmation keys)
            keys_to_update = []
            
            # Check each key in this timeframe
            for key in tf_data.keys():
                # Check if this key matches the exact 'to_key' or is a pattern key that contains it
                if key == to_key or key.endswith(f"_{to_key}") or key == f"{new_folder_name}_{to_key}":
                    keys_to_update.append(key)
                # Also check for confirmation keys that might contain the target pattern
                elif "_confirmation_from_" in key and to_key in key:
                    keys_to_update.append(key)
            
            if not keys_to_update:
                continue
            
            log(f"\n  📁 Timeframe: {tf}")
            
            # For each key to update, process its candles
            for target_key in keys_to_update:
                target_candles = tf_data.get(target_key, [])
                
                if not target_candles:
                    log(f"     ⏭️ Key '{target_key}' has no candle data")
                    continue
                
                # Debug: Show first candle's current swing_type
                if target_candles and len(target_candles) > 0:
                    first_candle = target_candles[0]
                    first_candle_time = first_candle.get('time', 'N/A')
                    first_candle_number = first_candle.get('candle_number', 'N/A')
                    first_swing_type = first_candle.get('swing_type', 'N/A')
                    log(f"\n     📍 Processing key: '{target_key}'")
                    log(f"        Example candle #{first_candle_number} (time: {first_candle_time[:50] if first_candle_time != 'N/A' else 'N/A'}...)")
                    log(f"        Current swing_type: {first_swing_type}")
                
                # Now we need to access the source data (from_key) for this timeframe
                # Source data path: dev_base_path/{sym}/{tf}/config.json
                source_config_path = os.path.join(dev_base_path, sym, tf, "config.json")
                
                if not os.path.exists(source_config_path):
                    log(f"        ⚠️ Source config not found: {source_config_path}")
                    continue
                
                try:
                    with open(source_config_path, 'r', encoding='utf-8') as f:
                        source_data = json.load(f)
                    
                    # Get the source candles from the from_key
                    source_candles = source_data.get(from_key, [])
                    
                    if not source_candles:
                        log(f"        ⚠️ Source key '{from_key}' not found or empty in {source_config_path}")
                        continue
                    
                    # Build lookup dictionaries for quick access by candle_number and time
                    source_by_candle_number = {}
                    source_by_timestamp = {}
                    
                    for candle in source_candles:
                        candle_number = candle.get('candle_number')
                        timestamp = candle.get('time')
                        
                        if candle_number is not None:
                            source_by_candle_number[candle_number] = candle
                        if timestamp:
                            source_by_timestamp[timestamp] = candle
                    
                    log(f"        ✅ Loaded {len(source_candles)} candles from source key '{from_key}'")
                    
                    # Update each target candle if matching source found
                    candles_updated_in_key = 0
                    
                    for i, target_candle in enumerate(target_candles):
                        target_candle_number = target_candle.get('candle_number')
                        target_timestamp = target_candle.get('time')
                        
                        # Try to find source candle by candle_number first, then by timestamp
                        source_candle = None
                        match_method = None
                        
                        if target_candle_number is not None and target_candle_number in source_by_candle_number:
                            source_candle = source_by_candle_number[target_candle_number]
                            match_method = f"candle_number {target_candle_number}"
                        elif target_timestamp and target_timestamp in source_by_timestamp:
                            source_candle = source_by_timestamp[target_timestamp]
                            match_method = "timestamp"
                        
                        if source_candle:
                            source_swing_type = source_candle.get('swing_type')
                            
                            if source_swing_type is not None:
                                # Get current swing_type for comparison
                                current_swing_type = target_candle.get('swing_type')
                                
                                # Only update if different
                                if current_swing_type != source_swing_type:
                                    # Update the swing_type
                                    target_candle['swing_type'] = source_swing_type
                                    target_candles[i] = target_candle  # Update in place
                                    candles_updated_in_key += 1
                                    total_candles_updated += 1
                                    
                                    # Debug output for first few updates
                                    if candles_updated_in_key <= 3:
                                        log(f"           🔄 Updated candle #{target_candle_number} (time: {target_timestamp[:50] if target_timestamp else 'N/A'}...)")
                                        log(f"              Swing_type: {current_swing_type} → {source_swing_type} (matched by {match_method})")
                    
                    if candles_updated_in_key > 0:
                        # Update the key in tf_data
                        tf_data[target_key] = target_candles
                        modified = True
                        log(f"        ✅ Updated {candles_updated_in_key} candles in '{target_key}'")
                        
                        # Show updated first candle as confirmation
                        if target_candles and len(target_candles) > 0:
                            updated_first = target_candles[0]
                            updated_swing_type = updated_first.get('swing_type', 'N/A')
                            log(f"        📊 After update: First candle swing_type = {updated_swing_type}")
                    else:
                        log(f"        ⏭️ No matching source candles found for '{target_key}'")
                        
                except Exception as e:
                    log(f"         Error processing {source_config_path}: {e}")
        
        # Also check confirmation data that might have been moved to target timeframes
        # The populate_other_timeframes_with_confirmation_entry might have created backup keys
        # We need to ensure any confirmation data also gets updated
        
        # Re-scan all timeframes again to catch any newly created/updated keys
        for tf, tf_data in list(target_data.items()):
            if not isinstance(tf_data, dict):
                continue
                
            # Look for backup keys that might contain the target pattern
            for key in list(tf_data.keys()):
                if key.startswith("backup") and to_key in key:
                    backup_candles = tf_data.get(key, [])
                    if backup_candles:
                        log(f"\n  📁 Checking backup key: '{key}' in {tf}")
                        
                        # Process backup data similarly
                        source_config_path = os.path.join(dev_base_path, sym, tf, "config.json")
                        if os.path.exists(source_config_path):
                            try:
                                with open(source_config_path, 'r', encoding='utf-8') as f:
                                    source_data = json.load(f)
                                
                                source_candles = source_data.get(from_key, [])
                                if source_candles:
                                    # Build lookup
                                    source_by_candle_number = {}
                                    source_by_timestamp = {}
                                    for candle in source_candles:
                                        candle_number = candle.get('candle_number')
                                        timestamp = candle.get('time')
                                        if candle_number is not None:
                                            source_by_candle_number[candle_number] = candle
                                        if timestamp:
                                            source_by_timestamp[timestamp] = candle
                                    
                                    # Update backup candles
                                    backup_updated = 0
                                    for i, backup_candle in enumerate(backup_candles):
                                        target_candle_number = backup_candle.get('candle_number')
                                        target_timestamp = backup_candle.get('time')
                                        
                                        source_candle = None
                                        if target_candle_number is not None and target_candle_number in source_by_candle_number:
                                            source_candle = source_by_candle_number[target_candle_number]
                                        elif target_timestamp and target_timestamp in source_by_timestamp:
                                            source_candle = source_by_timestamp[target_timestamp]
                                        
                                        if source_candle:
                                            source_swing_type = source_candle.get('swing_type')
                                            if source_swing_type is not None and backup_candle.get('swing_type') != source_swing_type:
                                                backup_candle['swing_type'] = source_swing_type
                                                backup_candles[i] = backup_candle
                                                backup_updated += 1
                                                total_candles_updated += 1
                                    
                                    if backup_updated > 0:
                                        tf_data[key] = backup_candles
                                        modified = True
                                        log(f"        ✅ Updated {backup_updated} candles in backup key '{key}'")
                            except Exception as e:
                                log(f"         Error processing backup {key}: {e}")
        
        if total_candles_updated > 0:
            log(f"\n  ✅ SWING TYPE SWAPPING COMPLETE: Updated {total_candles_updated} candles across all timeframes for {sym}")
        else:
            log(f"\n  ⏭️ No swing type updates performed for {sym}")
        
        return modified

    def process_entry_newfilename(entry_settings, source_def_name, raw_filename_base, base_folder, dev_base_path, symbols_dictionary=None):
        new_folder_name = entry_settings.get("new_filename")
        if not new_folder_name:
            return 0
        
        # --- FIXED: Symbol Filtering Logic (CASE INSENSITIVE) ---
        # Use the passed symbols_dictionary or fall back to entry_settings
        if symbols_dictionary is None:
            symbols_dictionary = entry_settings.get("symbols_dictionary", {})
        
        # Check if new_folder_name exists as a key in symbols_dictionary (case insensitive)
        target_symbols = None
        
        # Convert new_folder_name to lowercase for comparison
        new_folder_name_lower = new_folder_name.lower()
        
        # Look for matching key (case insensitive)
        matching_key = None
        for key in symbols_dictionary.keys():
            if key.lower() == new_folder_name_lower:
                matching_key = key
                break
        
        if matching_key:
            symbol_groups = symbols_dictionary[matching_key]
            log(f"{new_folder_name} targets specific symbols")
            
            # Collect all symbols from all groups in this entry
            all_symbols = []
            if isinstance(symbol_groups, dict):
                for group_name, symbol_list in symbol_groups.items():
                    if isinstance(symbol_list, list):
                        all_symbols.extend(symbol_list)
            elif isinstance(symbol_groups, list):
                # Handle case where value is directly a list
                all_symbols = symbol_groups
                log(f"  Direct symbol list: {symbol_groups}")
            
            # If we found any symbols, use them for filtering
            if all_symbols:
                target_symbols = set(all_symbols)
            else:
                log(f"{matching_key} activates processing all symbols")
        else:
            log(f"{new_folder_name} accepts all symbols")
        
        mark_paused_symbols_in_full_candles(dev_base_path, new_folder_name)
        identify_paused_symbols_poi(dev_base_path, new_folder_name)
        cleanup_non_paused_symbols(dev_base_path, new_folder_name)

        limit_orders_old_record_cleanup(dev_base_path, new_folder_name)

        # 2. Identify which symbols should be skipped (Paused Symbols)
        paused_symbols_file = os.path.join(dev_base_path, new_folder_name, "paused_symbols_folder", "paused_symbols.json")
        paused_names = set()
        
        if os.path.exists(paused_symbols_file):
            try:
                with open(paused_symbols_file, 'r', encoding='utf-8') as f:
                    paused_list = json.load(f)
                    paused_names = {item.get("symbol") for item in paused_list if "symbol" in item}
            except Exception as e:
                log(f"Error loading paused symbols: {e}")

        process_receiver = str(entry_settings.get("process_receiver_files", "no")).lower()
        identify_config = entry_settings.get("identify_definitions", {})
        poi_config = entry_settings.get("point_of_interest")  # Moved this up for clarity
        sync_count = 0

        # --- CHECK IF ENTRY CONFIRMATION IS ENABLED ---
        # Get the entry confirmation setting from accountmanagement
        entry_confirmation_enabled = entry_settings.get("enable_entry_poi_confirmation", False)
        if entry_confirmation_enabled:
            log(f"  ✅ Entry POI Confirmation is ENABLED for {new_folder_name}")
        else:
            log(f"  ⏭️ Entry POI Confirmation is DISABLED for {new_folder_name} - skipping confirmation processing")

        # Log filtering status before processing
        if target_symbols:
            log(f"🚀 PROCESSING ONLY these symbols for {new_folder_name}: {sorted(target_symbols)}")
        else:
            log(f"📁 Processing ALL symbols for {new_folder_name} (no filtering)")

        # 3. Iterate through symbols in the base folder
        for sym in sorted(os.listdir(base_folder)):
            sym_p = os.path.join(base_folder, sym)
            
            if not os.path.isdir(sym_p):
                continue
                
            # --- FIXED: Apply symbol filtering if target_symbols is set ---
            if target_symbols is not None:
                if sym not in target_symbols:
                    #log(f"  ⏭️ Skipping {sym} - not in target list")
                    continue  # Skip this symbol if it's not in the target list
                
            if sym in paused_names:
                log(f"  ⏸️ Skipping {sym} - paused")
                continue

            #log(f"  ✅ Processing {sym}")
            
            target_sym_dir = os.path.join(dev_base_path, new_folder_name, sym)
            os.makedirs(target_sym_dir, exist_ok=True)
            
            target_config_path = os.path.join(target_sym_dir, "config.json")
            target_data = {}
            if os.path.exists(target_config_path):
                try:
                    with open(target_config_path, 'r', encoding='utf-8') as f:
                        target_data = json.load(f)
                except Exception:
                    target_data = {}

            modified = False
            pending_images = {}
            pending_full_candle_data = {}

            # --- STEP 1: Process all timeframes for this symbol ---
            for tf in os.listdir(sym_p):
                tf_p = os.path.join(sym_p, tf)
                if not os.path.isdir(tf_p): 
                    continue
                
                source_dev_dir = os.path.join(dev_base_path, sym, tf)
                
                # MODIFIED: Instead of reading full_candles_data.json, we'll store a reference to where
                # this data will be stored in config.json after processing
                source_config_path = os.path.join(source_dev_dir, "config.json")
                if not os.path.exists(source_config_path): 
                    continue

                with open(source_config_path, 'r', encoding='utf-8') as f:
                    src_data = json.load(f)

                if tf not in target_data:
                    target_data[tf] = {}

                for file_key, candles in src_data.items():
                    clean_key = file_key.lower()
                    if "candle_list" in clean_key or "candlelist" in clean_key: 
                        continue

                    is_primary = (clean_key == source_def_name.lower() or clean_key == raw_filename_base)
                    is_receiver = (not is_primary and raw_filename_base in clean_key)

                    if (is_receiver and process_receiver != "yes") or (not is_primary and not is_receiver):
                        continue

                    new_key = f"{new_folder_name}_{file_key}"
                    
                    # --- MOVED: Call swing_points_liquidity BEFORE identify_definitions ---
                    # This needs to happen first to identify swing points in the raw candles
                    if poi_config and identify_config:
                        # First, call swing_points_liquidity on the original candles
                        swing_points_liquidity(target_data[tf], new_key, candles, identify_config)
                    
                    # Now proceed with identification and confirmation setup
                    if entry_confirmation_enabled:
                        full_candles_ref_key = f"{tf}_full_candles_ref_{file_key}"
                        pending_full_candle_data[full_candles_ref_key] = {
                            "tf": tf,
                            "config_key": file_key,  # The original key in the source config
                            "target_data_ref": target_data[tf],  # Reference to where it will be stored
                            "target_key": file_key  # In target_data, it will be stored under this key
                        }

                    processed_candles = {}
                    if identify_config:
                        processed_candles = identify_definitions({file_key: candles}, identify_config, source_def_name, raw_filename_base)
                        if file_key in processed_candles:
                            updated_candles, extracted_patterns = apply_definitions_condition(processed_candles[file_key], identify_config, new_folder_name, file_key)
                            target_data[tf][new_key] = updated_candles
                            if extracted_patterns:
                                target_data[tf][f"{new_key}_patterns"] = extracted_patterns
                                
                                # --- ADDED: Call add_liquidity_sweepers_to_patterns immediately after patterns are created ---
                                # Get original candles for liquidity sweepers
                                original_candles = candles
                                if original_candles:
                                    add_liquidity_sweepers_to_patterns(target_data[tf], new_key, original_candles)
                                    
                                    # --- ADDED: Call liquidity_flags_to_sweepers immediately after adding sweepers ---
                                    patterns_key = f"{new_key}_patterns"
                                    if patterns_key in target_data[tf]:
                                        liquidity_flags_to_sweepers(target_data[tf], patterns_key, identify_config)
                                
                            modified = True

                        processed_candles = intruder_and_outlaw_check(processed_candles)
                        
                        # Now apply POI functions after definitions have been identified
                        if poi_config and file_key in processed_candles:
                            # Note: swing_points_liquidity already called above
                            identify_poi(target_data[tf], new_key, candles, poi_config)
                            identify_poi_mitigation(target_data[tf], new_key, poi_config)
                            
                            identify_swing_mitigation_between_definitions(target_data[tf], new_key, candles, poi_config)
                            identify_selected(target_data[tf], new_key, poi_config)
                            # --- NEW: Remove outlawed swings between definitions ---
                            # This must be called AFTER identify_selected and BEFORE POI drawing
                            # It checks the FULL candle data for any swing between definitions
                            remove_outlawed_swings_in_between_definitions(
                                target_data[tf], 
                                new_key, 
                                candles,  # Pass the FULL original candles
                                poi_config
                            )

                    # Always store the original candles
                    target_data[tf][file_key] = candles
                    if identify_config and file_key in processed_candles:
                        target_data[tf][new_key] = processed_candles[file_key]
                    modified = True

            # --- STEP 2: Process Ticks JSON ---
            source_ticks_path = os.path.join(dev_base_path, sym, f"{sym}_ticks.json")
            if os.path.exists(source_ticks_path):
                target_ticks_path = os.path.join(target_sym_dir, f"{sym}_ticks.json")
                try:
                    with open(source_ticks_path, 'r', encoding='utf-8') as f:
                        ticks_data = json.load(f)
                    with open(target_ticks_path, 'w', encoding='utf-8') as f:
                        json.dump(ticks_data, f, indent=4)
                except Exception as e:
                    log(f"Error processing ticks for {sym}: {e}")
            
            # =================================================================
            # INTEGRATED SANITIZE LOGIC (replaces sanitize_symbols_or_files call)
            # =================================================================
            # Determine which timeframes have patterns
            tfs_to_keep = []
            tfs_to_remove = []

            for tf, tf_content in list(target_data.items()):
                has_patterns = any(key.endswith("_patterns") and value for key, value in tf_content.items())
                
                if has_patterns:
                    tfs_to_keep.append(tf)
                else:
                    tfs_to_remove.append(tf)

            # If no timeframes have patterns, the whole symbol is invalid - delete the folder
            if not tfs_to_keep:
                if os.path.exists(target_sym_dir):
                    shutil.rmtree(target_sym_dir)
                continue  # Skip to next symbol

            # =================================================================
            # END INTEGRATED SANITIZE LOGIC
            # =================================================================

            identify_paused_symbols(target_data, dev_base_path, new_folder_name)
            populate_limit_orders_with_paused_orders(dev_base_path, new_folder_name)
            
            # STEP 4 ADD DEFINITIONS LIQUIDITY TO PATTERNS (This section is now redundant but kept for backward compatibility)
            # Note: This section is kept but the main processing now happens immediately after pattern creation
            for tf in tfs_to_keep:
                if tf in target_data:
                    for file_key in list(target_data[tf].keys()):
                        if file_key.endswith("_patterns"):
                            base_key = file_key.replace("_patterns", "")
                            
                            # Extract original candles key from pattern key
                            if "_confirmation_from_" in base_key:
                                parts = base_key.split("_poi_")
                                if len(parts) > 1:
                                    original_candles_key = parts[1]
                                else:
                                    original_candles_key = base_key.split("_poi_")[0].split("_confirmation_from_")[1]
                            else:
                                original_candles_key = base_key.replace(f"{new_folder_name}_", "")
                            
                            original_candles = target_data[tf].get(original_candles_key, [])
                            
                            if original_candles:
                                add_liquidity_sweepers_to_patterns(target_data[tf], base_key, original_candles)
                                
                                # --- ADDED: Also add liquidity flags to sweepers for any patterns created here ---
                                if identify_config:
                                    liquidity_flags_to_sweepers(target_data[tf], file_key, identify_config)

            # --- STEP 5: Now create images WITH sweepers properly added ---
            for tf in os.listdir(sym_p):  # Re-iterate to create images
                tf_p = os.path.join(sym_p, tf)
                if not os.path.isdir(tf_p) or tf not in tfs_to_keep:
                    continue
                
                source_dev_dir = os.path.join(dev_base_path, sym, tf)
                source_config_path = os.path.join(source_dev_dir, "config.json")
                if not os.path.exists(source_config_path):
                    continue

                with open(source_config_path, 'r', encoding='utf-8') as f:
                    src_data = json.load(f)

                for file_key, candles in src_data.items():
                    clean_key = file_key.lower()
                    if "candle_list" in clean_key or "candlelist" in clean_key:
                        continue

                    is_primary = (clean_key == source_def_name.lower() or clean_key == raw_filename_base)
                    is_receiver = (not is_primary and raw_filename_base in clean_key)

                    if (is_receiver and process_receiver != "yes") or (not is_primary and not is_receiver):
                        continue

                    new_key = f"{new_folder_name}_{file_key}"
                    
                    # Image Handling
                    src_png = os.path.join(source_dev_dir, f"{file_key}.png")
                    if not os.path.exists(src_png):
                        src_png = os.path.join(source_dev_dir, f"{raw_filename_base}.png")

                    if os.path.exists(src_png):
                        img = cv2.imread(src_png)
                        if img is not None:
                            # Draw POI tools (now includes swing points liquidity from earlier)
                            if poi_config:
                                identify_candle_after_poi_and_apply_condition(target_data[tf], new_key, candles, poi_config, identify_config)
                                img = draw_poi_tools(img, target_data[tf], new_key, poi_config)
                                record_config = entry_settings.get("record_prices")
                                if record_config:
                                    identify_pending_prices(target_data[tf], new_key, record_config, dev_base_path, new_folder_name)
                                    
                                    # --- END ADDITION ---
                                    
                                    # --- ADDED: Call identify_hitler_prices immediately after identify_prices ---
                                    patterns_key = f"{new_key}_patterns"
                                    if patterns_key in target_data[tf]:
                                        identify_hitler_prices(
                                            target_data[tf], 
                                            new_key, 
                                            record_config,
                                            dev_base_path, 
                                            new_folder_name,
                                            target_data  # Pass the full target_data for cross-timeframe checking
                                        )
                                        mark_orders_with_candle_after_poi_and_switch_order_type(
                                            dev_base_path, 
                                            new_folder_name, 
                                            target_data[tf], 
                                            new_key, 
                                            sym,
                                            poi_config,  # Pass the POI config for switch rules
                                            record_config  # Pass the record_config for candle_after_poi_record_only flag
                                        )
                                        if record_config and record_config.get("hitler_poi_entry_condition"):
                                            apply_hitler_poi_entry_condition_to_orders(
                                                dev_base_path,
                                                new_folder_name,
                                                record_config
                                            )
                                                                    
                            # Draw definition tools AFTER sweepers and flags have been added
                            if identify_config:
                                patterns_key = f"{new_key}_patterns"
                                if patterns_key in target_data[tf]:
                                    # No need to call liquidity_flags_to_sweepers here as it's already done
                                    img = draw_definition_tools(img, target_data[tf], patterns_key, identify_config)
                            
                            img_filename = f"{tf}_{file_key}.png"
                            pending_images[img_filename] = (tf, img)

            # --- STEP 6: Extract POI to confirmation candles (ONLY IF ENABLED) ---
            # This now runs with the MERGED data
            if entry_confirmation_enabled:
                # Get the POI confirmation timeframes from entry settings
                poi_confirmation_timeframes = entry_settings.get("poi_confirmation_timeframes", {})
                
                for tf in tfs_to_keep:
                    if tf in target_data:
                        for file_key in list(target_data[tf].keys()):
                            if file_key.endswith("_patterns"):
                                # Extract base key (remove '_patterns' suffix)
                                base_key = file_key.replace("_patterns", "")
                                
                                # Call the POI extraction function for this pattern, passing pending_full_candle_data
                                original_target_data = target_data[tf].copy()  # Keep a copy for reference
                                result = extract_poi_to_confirmation(
                                    target_data[tf], 
                                    base_key, 
                                    dev_base_path, 
                                    new_folder_name, 
                                    sym,
                                    pending_full_candle_data,  # Pass the queued full candle references
                                    poi_confirmation_timeframes  # Pass the configuration
                                )
                                
                                # Check if anything was added/modified
                                if result != original_target_data:
                                    target_data[tf] = result
                                    modified = True

                # --- STEP 7: Generate confirmation charts for all timeframes (ONLY IF ENABLED) ---
                generate_confirmation_charts(
                    dev_base_path,
                    new_folder_name,
                    sym,
                    target_sym_dir,
                    target_data,
                    pending_full_candle_data,
                    tfs_to_keep  # Pass the list of timeframes to keep
                )

                # --- STEP 8: Move confirmation keys to their target timeframes (ONLY IF ENABLED) ---
                if move_confirmation_keys_to_target_timeframes(target_data, dev_base_path, new_folder_name, sym):
                    modified = True

                # --- STEP 9: Populate other timeframes with confirmation entry data (ONLY IF ENABLED) ---
                if populate_other_timeframes_with_confirmation_entry(target_data, dev_base_path, new_folder_name, sym):
                    modified = True

                # --- STEP 9.5: Swap swing type values if configured ---
                data_swapping_config = entry_settings.get("data_swapping")
                if data_swapping_config:
                    log(f"  🔄 Processing data_swapping for {sym}")
                    if swap_from_key_swing_type_values_to_target(target_data, dev_base_path, new_folder_name, sym, data_swapping_config):
                        modified = True
                else:
                    log(f"  ⏭️ No data_swapping configuration for {sym}")

            # --- STEP 10: Final Write (Images) ---
            # Write Images (only for timeframes that are kept)
            for img_name, (tf, img_data) in pending_images.items():
                if tf in tfs_to_keep:
                    cv2.imwrite(os.path.join(target_sym_dir, img_name), img_data)
                else:
                    full_path = os.path.join(target_sym_dir, img_name)
                    if os.path.exists(full_path): 
                        os.remove(full_path)

            if modified:
                with open(target_config_path, 'w', encoding='utf-8') as f:
                    json.dump(target_data, f, indent=4)
                sync_count += 1

        # --- FINAL STEP: Clear limit orders at the END if confirmation is enabled ---
        if entry_confirmation_enabled:
            #do nothing until decision
            
            # --- NEW: Identify and save Hitler/POI prices using the same record_config ---
            log(f"  🎯 Identifying POI Zone for {new_folder_name} entries")
            record_config = entry_settings.get("record_prices")  # Use the same record_config as limit orders
            
            if record_config:
                # First, clear the existing poi_entry.json to start fresh
                orders_dir = os.path.join(dev_base_path, new_folder_name, "pending_orders")
                poi_file = os.path.join(orders_dir, "poi_entry.json")
                if os.path.exists(poi_file):
                    try:
                        os.remove(poi_file)
                        log(f"    🧹 Cleared existing poi_entry.json")
                    except:
                        pass
                
                # Iterate through all symbols and timeframes to identify hitler prices
                for sym in sorted(os.listdir(base_folder)):
                    sym_p = os.path.join(base_folder, sym)
                    if not os.path.isdir(sym_p):
                        continue
                        
                    target_sym_dir = os.path.join(dev_base_path, new_folder_name, sym)
                    target_config_path = os.path.join(target_sym_dir, "config.json")
                    
                    if os.path.exists(target_config_path):
                        try:
                            with open(target_config_path, 'r', encoding='utf-8') as f:
                                target_data = json.load(f)
                            
                            # Process each timeframe
                            for tf in target_data.keys():
                                if isinstance(target_data[tf], dict):
                                    for key in target_data[tf].keys():
                                        if key.endswith("_patterns"):
                                            # Call identify_hitler_prices for each pattern key
                                            # Pass the FULL target_data so it can check across all timeframes
                                            identify_hitler_prices(
                                                target_data[tf], 
                                                key.replace("_patterns", ""), 
                                                record_config,
                                                dev_base_path, 
                                                new_folder_name,
                                                target_data  # Pass the full target_data for cross-timeframe checking
                                            )
                        except Exception as e:
                            log(f"Error processing hitler prices for {sym}: {e}")
            else:
                log(f"  ⚠️ No record_config found for {new_folder_name}, skipping Hitler/POI identification")
        else:
            filter_empty_symbol_folders(dev_base_path, new_folder_name)
            log(f"  💾 Preserving limit orders for {new_folder_name} (confirmation disabled)")
            

        # --- NEW: Log summary of filtered processing ---
        if target_symbols:
            log(f"✅ PROCESSED {new_folder_name} {sync_count} ENTRIES POI")
            
        return sync_count

    def main_logic():
        """Main logic for processing entry points of interest."""
        log(f"Starting: {user_id}")

        dev_dict = load_developers_dictionary() 
        cfg = dev_dict.get(str(user_id))
        if not cfg:
            log(f"User {user_id} not found")
            return f"Error: User {user_id} not in dictionary."
        
        # Use DEV_PATH from your main config
        dev_base_path = os.path.join(DEV_PATH, str(user_id))
        base_folder = os.path.join(dev_base_path, "ohlc")
        
        # Get accountmanagement from developers.json (NOT from file system)
        am_data = get_account_management(str(user_id))
        if not am_data:
            log("accountmanagement configuration missing in developers.json")
            return "Error: accountmanagement configuration missing in developers.json."

        # Get symbols_dictionary from accountmanagement (already loaded from developers.json)
        symbols_dictionary = am_data.get("symbols_dictionary", {})

        define_candles = am_data.get("chart", {}).get("define_candles", {})
        entries_root = define_candles.get("entries_poi_condition", {})
        
        total_syncs = 0
        entry_count = 0

        for apprehend_key, source_configs in entries_root.items():
            if not apprehend_key.startswith("apprehend_"):
                continue
                
            source_def_name = apprehend_key.replace("apprehend_", "")
            source_def = define_candles.get(source_def_name, {})
            if not source_def:
                continue

            raw_filename_base = source_def.get("filename", "").replace(".json", "").lower()

            for entry_key, entry_settings in source_configs.items():
                if not entry_key.startswith("entry_"):
                    continue

                new_folder_name = entry_settings.get('new_filename')
                if new_folder_name:
                    print()
                    log(f"\n📊 PROCESSING {new_folder_name}")
                    
                    identify_config = entry_settings.get("identify_definitions")
                    if identify_config:
                        log(f"  With identify_definitions: {list(identify_config.keys())}")
                    
                    entry_count += 1
                    
                    syncs = process_entry_newfilename(
                        entry_settings, 
                        source_def_name, 
                        raw_filename_base, 
                        base_folder,
                        dev_base_path,
                        symbols_dictionary
                    )
                    
                    total_syncs += syncs
        
        if entry_count > 0:
            return f"Completed: {entry_count} entry points processed, {total_syncs} total syncs"
        else:
            return f"No entry points found for processing."
    # ---- Execute Main Logic ---- 3
    return main_logic()

def entries_confirmation(user_id):
    lagos_tz = pytz.timezone('Africa/Lagos') 
    
    
    def log(msg, level="INFO"):
        ts = datetime.now(lagos_tz).strftime('%H:%M:%S')
        print(f"[{ts}] {msg}")

    def get_max_candle_count(dev_base_path, timeframe):
        """Helper to find candle count. Returns 0 if config is null or missing."""
        config_path = os.path.join(dev_base_path, "accountmanagement.json")
        max_days = 0  # Default to 0 so missing file/error clears records
        
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # .get("chart", {}) returns empty dict if "chart" is missing
                    # .get("maximum_holding_days") returns None if key is missing or null
                    val = config.get("chart", {}).get("maximum_holding_days")
                    
                    if val is not None:
                        max_days = val
                    else:
                        max_days = 0 # Handle explicit null or missing key
        except Exception:
            max_days = 0 # Fallback on error to ensure clearing logic triggers

        # Conversion map
        tf_map = {
            "1m": 1, "5m": 5, "10m": 10, "15m": 15, "30m": 30,
            "1h": 60, "4h": 240, "1d": 1440
        }
        
        mins_per_candle = tf_map.get(timeframe.lower(), 1)
        total_minutes_in_period = max_days * 24 * 60
        return total_minutes_in_period // mins_per_candle
    
    def mark_paused_symbols_in_full_candles(dev_base_path, new_folder_name):
        paused_folder = os.path.join(dev_base_path, new_folder_name, "paused_symbols_folder")
        paused_file = os.path.join(paused_folder, "paused_symbols.json")
        
        if not os.path.exists(paused_file):
            return

        # --- IMMEDIATE FIX: Global Config Check ---
        # We check a dummy timeframe ('1m') just to see if the user set max_days to 0
        # because if max_days is 0, it's 0 for all timeframes.
        global_threshold = get_max_candle_count(dev_base_path, "1m")
        if global_threshold <= 0:
            try:
                with open(paused_file, 'w', encoding='utf-8') as f:
                    json.dump([], f, indent=4)
                # log("Global threshold is 0: Paused symbols file cleared.")
                return # Exit early so no other logic restores the records
            except Exception as e:
                print(f"Error clearing paused file: {e}")
                return

        # --- Standard logic continues if threshold > 0 ---
        try:
            with open(paused_file, 'r', encoding='utf-8') as f:
                paused_records = json.load(f)
        except Exception as e:
            print(f"Error reading paused symbols: {e}")
            return

        updated_paused_records = []
        records_removed = False
        markers_map = {}

        for record in paused_records:
            sym, tf = record.get("symbol"), record.get("timeframe")
            if sym and tf:
                markers_map.setdefault((sym, tf), []).append(record)

        for (sym, tf), records in markers_map.items():
            max_allowed_count = get_max_candle_count(dev_base_path, tf)
            
            # This part handles specific TF logic if max_allowed_count varies
            if max_allowed_count <= 0:
                records_removed = True
                continue

            full_candle_path = os.path.join(dev_base_path, new_folder_name, sym, f"{tf}_full_candles_data.json")
            
            if not os.path.exists(full_candle_path):
                updated_paused_records.extend(records)
                continue

            try:
                with open(full_candle_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                if not isinstance(data, list) or not data:
                    updated_paused_records.extend(records)
                    continue

                candles = data[1:] if (len(data) > 0 and "summary" in data[0]) else data
                total_candles = len(candles)
                summary = {}
                current_tf_records_to_keep = []

                for rec in records:
                    from_time = rec.get("time")
                    after_data = rec.get("after", {})
                    after_time = after_data.get("time")
                    entry_val = rec.get("entry")
                    order_type = rec.get("order_type")

                    clean_from = from_time.replace(':', '-').replace(' ', '_')
                    clean_after = after_time.replace(':', '-').replace(' ', '_') if after_time else "N/A"
                    
                    should_remove_this_record = False
                    final_count_ahead = 0
                    final_remaining = 0

                    for idx, candle in enumerate(candles):
                        c_time = candle.get("time")
                        if c_time == from_time:
                            candle[f"from_{clean_from}"] = True
                            candle["entry"] = entry_val
                            candle["order_type"] = order_type

                        if after_time and c_time == after_time:
                            count_ahead = total_candles - (idx + 1)
                            remaining = max_allowed_count - count_ahead
                            final_count_ahead = count_ahead
                            final_remaining = remaining

                            if count_ahead >= max_allowed_count:
                                should_remove_this_record = True
                                records_removed = True
                            
                            candle[f"after_{clean_after}"] = True
                            candle[f"connected_with_{clean_from}"] = True
                            candle["candles_count_ahead_after_candle"] = count_ahead
                            candle["remaining_candles_to_threshold"] = remaining

                    if not should_remove_this_record:
                        current_tf_records_to_keep.append(rec)
                        conn_idx = len(current_tf_records_to_keep)
                        summary[f"connection_{conn_idx}"] = {
                            f"from_{clean_from}": entry_val,
                            "order_type": order_type,
                            "after_time": after_time,
                            "candles_count_ahead_after_candle": final_count_ahead,
                            "remaining_candles_to_threshold": final_remaining
                        }

                final_output = [{"summary": summary}] + candles
                with open(full_candle_path, 'w', encoding='utf-8') as f:
                    json.dump(final_output, f, indent=4)
                
                updated_paused_records.extend(current_tf_records_to_keep)

            except Exception as e:
                print(f"Error processing {sym} {tf}: {e}")
                updated_paused_records.extend(records)

        if records_removed:
            with open(paused_file, 'w', encoding='utf-8') as f:
                json.dump(updated_paused_records, f, indent=4)

    def identify_paused_symbols_poi(dev_base_path, new_folder_name):
        """
        Analyzes full_candles_data.json to find price violations (hitler candles)
        for paused records. Removes symbols from paused list when violation is found.
        """
        paused_folder = os.path.join(dev_base_path, new_folder_name, "paused_symbols_folder")
        paused_file = os.path.join(paused_folder, "paused_symbols.json")
        
        if not os.path.exists(paused_file):
            return

        try:
            with open(paused_file, 'r', encoding='utf-8') as f:
                paused_records = json.load(f)
        except Exception as e:
            log(f"Error reading paused symbols for POI: {e}")
            return

        # Group by symbol/tf to minimize file I/O
        markers_map = {}
        for record in paused_records:
            sym, tf = record.get("symbol"), record.get("timeframe")
            if sym and tf:
                markers_map.setdefault((sym, tf), []).append(record)

        updated_paused_records = []  # Will hold records that should remain paused
        records_removed = False

        for (sym, tf), records in markers_map.items():
            full_candle_path = os.path.join(dev_base_path, new_folder_name, sym, f"{tf}_full_candles_data.json")
            
            if not os.path.exists(full_candle_path):
                updated_paused_records.extend(records)
                continue

            try:
                with open(full_candle_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                if not isinstance(data, list) or len(data) < 2:
                    updated_paused_records.extend(records)
                    continue

                # Separate summary and candles
                summary_obj = data[0].get("summary", {})
                candles = data[1:]
                
                modified_summary = False
                records_to_keep_for_this_symbol = []  # Records that didn't trigger hitler

                # Process each connection defined in the summary
                for conn_key, conn_val in summary_obj.items():
                    # Extract 'after_time' and 'order_type' to determine logic
                    after_time = conn_val.get("after_time")
                    order_type = conn_val.get("order_type")
                    
                    # Find the 'from' key to get the entry price
                    from_key = next((k for k in conn_val.keys() if k.startswith("from_")), None)
                    if not from_key or not after_time:
                        records_to_keep_for_this_symbol.append(conn_val)  # Keep if incomplete data
                        continue
                    
                    entry_price = conn_val[from_key]
                    hitler_found = False

                    # Search for price violation after the 'after' candle
                    search_active = False
                    for candle in candles:
                        c_time = candle.get("time")
                        
                        if not search_active:
                            if c_time == after_time:
                                search_active = True
                            continue
                        
                        c_num = candle.get("candle_number", "unknown")
                        
                        if "buy" in order_type.lower():
                            low_val = candle.get("low")
                            if low_val is not None and low_val < entry_price:
                                label = f"hitlercandle{c_num}_ahead_after_candle_breaches_from_low_price_{entry_price}"
                                conn_val[label] = True
                                hitler_found = True
                                records_removed = True  # Mark for removal from paused list
                                break
                        
                        elif "sell" in order_type.lower():
                            high_val = candle.get("high")
                            if high_val is not None and high_val > entry_price:
                                label = f"hitlercandle{c_num}_ahead_after_candle_breaches_from_high_price_{entry_price}"
                                conn_val[label] = True
                                hitler_found = True
                                records_removed = True  # Mark for removal from paused list
                                break

                    if not hitler_found:
                        conn_val["no_hitler"] = True
                        # Find and keep the original paused record that matches this connection
                        matching_record = next(
                            (r for r in records if r.get("after", {}).get("time") == after_time),
                            None
                        )
                        if matching_record:
                            records_to_keep_for_this_symbol.append(matching_record)
                    
                    modified_summary = True

                # Add records that should remain paused to the global list
                updated_paused_records.extend(records_to_keep_for_this_symbol)

                # Save the updated candles with hitler markers
                if modified_summary:
                    data[0]["summary"] = summary_obj
                    with open(full_candle_path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=4)

            except Exception as e:
                log(f"Error in identify_paused_symbols_poi for {sym} {tf}: {e}")
                updated_paused_records.extend(records)  # Keep records on error

        # Update paused file if any records were removed
        if records_removed:
            with open(paused_file, 'w', encoding='utf-8') as f:
                json.dump(updated_paused_records, f, indent=4)
            log(f"Removed {len(paused_records) - len(updated_paused_records)} symbols from paused list due to price violations")

    def swing_points_liquidity(target_data_tf, new_key, original_candles, identify_config):
        """
        Identifies liquidity sweepers directly from original candles for ALL swing points.
        For Lower Low: finds first candle with low lower than the swing low's low
        For Higher High: finds first candle with high higher than the swing high's high
        Marks both victims and sweepers directly on the original candle records.
        
        Victim gets marked with:
            - swept_by_liquidity: true
            - swept_by_candle_number: [sweeper candle number]
            - swept_by_candles: [list of sweeper candle numbers]
        
        Sweeper gets marked with:
            - is_liquidity_sweep: true
            - swept_victims: [list of victim candle numbers]
            - swept_victim_number: [first/primary victim]
        """
        if not identify_config or not isinstance(target_data_tf, dict) or not original_candles:
            return
        
        # First, identify ALL swing candles as potential victims (swing_lows and swing_highs)
        victims = []  # List of (candle_number, swing_type, target_price)
        
        for candle in original_candles:
            if not isinstance(candle, dict):
                continue
                
            swing_type = candle.get("swing_type", "").lower()
            candle_num = candle.get("candle_number")
            
            if not swing_type or candle_num is None:
                continue
            
            # Consider ALL swing_low and swing_high as potential victims
            if swing_type == "swing_low":
                target_price = candle.get("low")
                if target_price is not None:
                    victims.append((candle_num, swing_type, target_price))
                    #log(f"    📍 Found victim candidate: Candle {candle_num} | Type: swing_low | Price: {target_price:.5f}")
                    
            elif swing_type == "swing_high":
                target_price = candle.get("high")
                if target_price is not None:
                    victims.append((candle_num, swing_type, target_price))
                    #log(f"    📍 Found victim candidate: Candle {candle_num} | Type: swing_high | Price: {target_price:.5f}")
        
        
        #log(f"  🔍 LIQUIDITY SWEEP: Found {len(victims)} swing candles to check for sweepers")
        
        # Track relationships
        sweeper_to_victims = {}  # sweeper_num -> list of victim_nums
        victim_to_sweepers = {}  # victim_num -> list of sweeper_nums
        
        # For each swing candle, find its sweeper
        for victim_num, swing_type, target_price in victims:
            
            # Find the FIRST candle after the victim that sweeps it
            sweeper_num = None
            
            for candle in original_candles:
                if not isinstance(candle, dict):
                    continue
                    
                candle_num = candle.get("candle_number")
                if candle_num is None or candle_num <= victim_num:
                    continue
                
                if swing_type == "swing_low":
                    candle_price = candle.get("low")
                    if candle_price is not None and candle_price < target_price:
                        sweeper_num = candle_num
                        #log(f"      ✅ Sweeper found: Candle {candle_num} low ({candle_price:.5f}) < victim low ({target_price:.5f})")
                        break
                        
                elif swing_type == "swing_high":
                    candle_price = candle.get("high")
                    if candle_price is not None and candle_price > target_price:
                        sweeper_num = candle_num
                        #log(f"      ✅ Sweeper found: Candle {candle_num} high ({candle_price:.5f}) > victim high ({target_price:.5f})")
                        break
            
            if sweeper_num:
                # Record relationship
                if sweeper_num not in sweeper_to_victims:
                    sweeper_to_victims[sweeper_num] = []
                if victim_num not in sweeper_to_victims[sweeper_num]:
                    sweeper_to_victims[sweeper_num].append(victim_num)
                
                if victim_num not in victim_to_sweepers:
                    victim_to_sweepers[victim_num] = []
                if sweeper_num not in victim_to_sweepers[victim_num]:
                    victim_to_sweepers[victim_num].append(sweeper_num)
                
                #log(f"      📝 Relationship: Victim {victim_num} <- Sweeper {sweeper_num}")
        
        # Mark the original candles
        victims_marked = 0
        sweepers_marked = 0
        
        # Mark victims
        for victim_num, sweeper_list in victim_to_sweepers.items():
            for candle in original_candles:
                if isinstance(candle, dict) and candle.get("candle_number") == victim_num:
                    candle["swept_by_liquidity"] = True
                    candle["swept_by_candle_number"] = sweeper_list[0]
                    candle["swept_by_candles"] = sweeper_list
                    victims_marked += 1
                    #log(f"    🎯 Marked victim candle {victim_num} swept by: {sweeper_list}")
                    break
        
        # Mark sweepers
        for sweeper_num, victim_list in sweeper_to_victims.items():
            for candle in original_candles:
                if isinstance(candle, dict) and candle.get("candle_number") == sweeper_num:
                    candle["is_liquidity_sweep"] = True
                    candle["swept_victims"] = victim_list
                    candle["swept_victim_number"] = victim_list[0]
                    sweepers_marked += 1
                    #log(f"    💧 Marked sweeper candle {sweeper_num} sweeping victims: {victim_list}")
                    break
        
        #log(f"  ✅ LIQUIDITY SWEEP: Found {len(sweeper_to_victims)} sweepers, marked {victims_marked} victims and {sweepers_marked} sweepers for {new_key}")
        # 
        #    
       
    def identify_definitions(candle_data, identify_config, source_def_name, raw_filename_base):
        if not identify_config:
            return candle_data
            
        processed_data = candle_data.copy()
        
        # Ordinal mapping for naming convention
        ordinals = ["zero", "first", "second", "third", "fourth", "fifth", "sixth", 
                    "seventh", "eighth", "ninth", "tenth", "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth", "seventeenth", "eighteenth", "nineteenth", "twenteenth"]

        # Sort definitions to ensure sequential processing (define_1, define_2...)
        definitions = sorted([(k, v) for k, v in identify_config.items() 
                            if k.startswith("define_")], 
                            key=lambda x: int(x[0].split('_')[1]))
        
        if not definitions:
            return processed_data

        def get_target_swing(current_type, logic_type):
            logic_type = logic_type.lower()
            if "opposite" in logic_type:
                return "swing_low" if current_type == "swing_high" else "swing_high"
            if "identical" in logic_type:
                return current_type
            return None

        for file_key, candles in processed_data.items():
            if not isinstance(candles, list): continue
            
            # --- GLOBAL LOOP: Every swing candle gets a turn to be the 'Anchor' (define_1) ---
            for i, anchor_candle in enumerate(candles):
                if not (isinstance(anchor_candle, dict) and "swing_type" in anchor_candle):
                    continue
                    
                s_type = anchor_candle.get("swing_type", "").lower()
                if s_type not in ["swing_high", "swing_low"]:
                    continue

                # Step 1: Initialize the chain with define_1
                def1_name = definitions[0][0]
                anchor_candle[def1_name] = True
                anchor_candle[f"{def1_name}_swing_type"] = s_type
                anchor_idx = anchor_candle.get("candle_number", i)
                
                # chain_history tracks the 'firstfound' of each step to determine the NEXT step's start point
                # Format: { def_name: (index_in_list, candle_object) }
                chain_history = {def1_name: (i, anchor_candle)}

                # Step 2: Process subsequent definitions (The Chain)
                for def_idx in range(1, len(definitions)):
                    curr_def_name, curr_def_config = definitions[def_idx]
                    prev_def_name, _ = definitions[def_idx - 1]
                    
                    # Logic dictates we start searching AFTER the 'firstfound' of the previous definition
                    if prev_def_name not in chain_history:
                        break
                    
                    prev_idx_in_list, prev_candle_obj = chain_history[prev_def_name]
                    search_start_idx = prev_idx_in_list + 1
                    
                    prev_swing_type = prev_candle_obj.get(f"{prev_def_name}_swing_type", "")
                    target_swing = get_target_swing(prev_swing_type, curr_def_config.get("type", ""))
                    
                    if not target_swing:
                        continue

                    found_count_for_this_step = 0
                    
                    # Search forward for ALL matches
                    for j in range(search_start_idx, len(candles)):
                        target_candle = candles[j]
                        if not (isinstance(target_candle, dict) and target_candle.get("swing_type")):
                            continue
                        
                        if target_candle["swing_type"].lower() == target_swing:
                            found_count_for_this_step += 1
                            curr_candle_num = target_candle.get("candle_number", j)
                            ref_candle_num = prev_candle_obj.get("candle_number", prev_idx_in_list)
                            
                            # Mark Base Flags
                            target_candle[curr_def_name] = True
                            target_candle[f"{curr_def_name}_swing_type"] = target_swing
                            
                            # Determine Ordinal (firstfound, secondfound, etc.)
                            if found_count_for_this_step < len(ordinals):
                                ord_str = f"{ordinals[found_count_for_this_step]}found"
                            else:
                                ord_str = f"{found_count_for_this_step}thfound"
                            
                            # Construct Dynamic Key
                            # e.g., define_2_firstfound_4_in_connection_with_define_1_1
                            conn_key = f"{curr_def_name}_{ord_str}_{curr_candle_num}_in_connection_with_{prev_def_name}_{ref_candle_num}"
                            
                            logic_label = "opposite" if "opposite" in curr_def_config.get("type", "").lower() else "identical"
                            target_candle[conn_key] = logic_label
                            
                            # If this is the FIRST one found for this step, 
                            # it becomes the anchor for the NEXT definition (define_N+1)
                            if found_count_for_this_step == 1:
                                chain_history[curr_def_name] = (j, target_candle)

                    # If no matches were found for this step, the chain for this anchor is broken
                    if found_count_for_this_step == 0:
                        break

        return processed_data

    def apply_definitions_condition(candles, identify_config, new_filename_value, file_key):
        if not identify_config or not isinstance(candles, list):
            return candles, {}

        # --- SECTION 1: DYNAMIC VALIDATION (The "Logic Check") ---
        for target_candle in candles:
            if not isinstance(target_candle, dict): continue
            conn_keys = [k for k in target_candle.keys() if "_in_connection_with_" in k]
            
            for conn_key in conn_keys:
                parts = conn_key.split('_')
                curr_def_base = f"{parts[0]}_{parts[1]}" 
                
                def_cfg = identify_config.get(curr_def_base, {})
                condition_cfg = def_cfg.get("condition", "").lower()
                if not condition_cfg: 
                    target_candle[f"{conn_key}_met"] = True
                    continue

                mode = "behind" if "behind" in condition_cfg else "beyond"
                target_match = re.search(r'define_(\d+)', condition_cfg)
                if not target_match: continue
                target_def_index = int(target_match.group(1))

                # Trace back to find the specific define_n ref candle
                ref_candle = None
                search_key = conn_key
                while True:
                    t_parts = search_key.split('_')
                    p_def_lvl = int(t_parts[8])
                    p_num = int(t_parts[9])
                    
                    if p_def_lvl == target_def_index:
                        ref_candle = next((c for c in candles if c.get("candle_number") == p_num), None)
                        break
                    
                    parent_candle = next((c for c in candles if c.get("candle_number") == p_num), None)
                    if not parent_candle: break
                    search_key = next((k for k in parent_candle.keys() if k.startswith(f"define_{p_def_lvl}_") and "_in_connection_" in k), None)
                    if not search_key: break

                if ref_candle:
                    ref_h, ref_l = ref_candle.get("high"), ref_candle.get("low")
                    r_type = ref_candle.get("swing_type", "").lower()
                    
                    # Helper function for the core price logic
                    def check_logic(c_type, c_h, c_l, r_type, r_h, r_l, mode):
                        if mode == "behind":
                            if c_type == "swing_high" and r_type == "swing_high": return c_h < r_h
                            if c_type == "swing_low" and r_type == "swing_low": return c_l > r_l
                            if c_type == "swing_high" and r_type == "swing_low": return c_l > r_h
                            if c_type == "swing_low" and r_type == "swing_high": return c_h < r_l
                        elif mode == "beyond":
                            if c_type == "swing_high" and r_type == "swing_high": return c_h > r_h
                            if c_type == "swing_low" and r_type == "swing_low": return c_l < r_l
                            if c_type == "swing_high" and r_type == "swing_low": return c_h > r_h
                            if c_type == "swing_low" and r_type == "swing_high": return c_l < r_l
                        return False

                    # 1. Check the target candle itself
                    curr_h, curr_l = target_candle.get("high"), target_candle.get("low")
                    c_type = target_candle.get("swing_type", "").lower()
                    
                    logic_met = check_logic(c_type, curr_h, curr_l, r_type, ref_h, ref_l, mode)

                    # 2. Check Collective Beyond Requirement
                    min_collective = def_cfg.get("minimum_collectivebeyondcandles")
                    if logic_met and mode == "beyond" and isinstance(min_collective, int) and min_collective > 0:
                        # Find index of current candle to look behind in the list
                        try:
                            curr_idx = candles.index(target_candle)
                            # Check the 'n' candles before this one
                            for i in range(1, min_collective + 1):
                                prev_idx = curr_idx - i
                                if prev_idx < 0:
                                    logic_met = False # Not enough history
                                    break
                                
                                prev_c = candles[prev_idx]
                                p_h, p_l = prev_c.get("high"), prev_c.get("low")
                                # We use the target's swing type for the collective check as they are "with" the target
                                if not check_logic(c_type, p_h, p_l, r_type, ref_h, ref_l, mode):
                                    logic_met = False
                                    break
                        except ValueError:
                            pass

                    if logic_met:
                        target_candle[f"{conn_key}_met"] = True

        # --- SECTION 2: EXTRACTION (The "Grouping") ---
        # (Rest of the function remains the same)
        def_nums = [int(k.split('_')[1]) for k in identify_config.keys() if k.startswith("define_")]
        max_def = max(def_nums) if def_nums else 0
        patterns_dict = {}
        pattern_idx = 1

        for candle in candles:
            if not isinstance(candle, dict): continue
            last_def_keys = [k for k in candle.keys() if k.startswith(f"define_{max_def}_") and k.endswith("_met")]
            for m_key in last_def_keys:
                current_family = [candle]
                is_valid_family = True
                current_trace_key = m_key
                for d in range(max_def, 1, -1):
                    p_parts = current_trace_key.split('_')
                    parent_num = int(p_parts[9])
                    parent_def_lvl = int(p_parts[8])
                    parent_candle = next((c for c in candles if c.get("candle_number") == parent_num), None)
                    if not parent_candle:
                        is_valid_family = False
                        break
                    if parent_def_lvl > 1:
                        parent_met_key = next((k for k in parent_candle.keys() if k.startswith(f"define_{parent_def_lvl}_") and k.endswith("_met")), None)
                        if not parent_met_key:
                            is_valid_family = False
                            break
                        current_trace_key = parent_met_key
                    current_family.insert(0, parent_candle)

                if is_valid_family:
                    unique_family = []
                    seen_nums = set()
                    for c in current_family:
                        if c['candle_number'] not in seen_nums:
                            unique_family.append(c)
                            seen_nums.add(c['candle_number'])
                    patterns_dict[f"pattern_{pattern_idx}"] = unique_family
                    pattern_idx += 1

        patterns_dict = sanitize_pattern_definitions(patterns_dict)
        return candles, patterns_dict

    def sanitize_pattern_definitions(patterns_dict):
        """
        Sanitizes each pattern in the dictionary.
        Ensures that the N-th candle in a pattern family only contains 'define_N' metadata.
        """
        if not patterns_dict:
            return {}

        sanitized_patterns = {}

        for p_name, family in patterns_dict.items():
            new_family = []
            
            # The family is ordered [define_1, define_2, ..., define_max]
            for idx, candle in enumerate(family):
                if not isinstance(candle, dict):
                    new_family.append(candle)
                    continue
                
                # Create a shallow copy to avoid modifying the original list in-place
                clean_candle = candle.copy()
                current_rank = idx + 1  # 1-based indexing for define_n
                
                # Identify keys to keep:
                # 1. Standard OHLCV and technical data
                # 2. 'define_N' keys specific to this candle's position in the pattern
                keys_to_delete = []
                
                for key in clean_candle.keys():
                    # If the key is a 'define_X' key
                    if key.startswith("define_"):
                        # Extract the number from 'define_N...'
                        try:
                            parts = key.split('_')
                            def_num = int(parts[1])
                            
                            # Logic: If this is the 2nd candle in the list, 
                            # it should ONLY have define_2 related keys.
                            if def_num != current_rank:
                                keys_to_delete.append(key)
                        except (ValueError, IndexError):
                            continue
                
                # Remove the non-relevant define keys
                for k in keys_to_delete:
                    del clean_candle[k]
                    
                new_family.append(clean_candle)
                
            sanitized_patterns[p_name] = new_family
            
        return sanitized_patterns

    def intruder_and_outlaw_check(processed_data):
        for file_key, candles in processed_data.items():
            if not isinstance(candles, list):
                continue

            for i, candle in enumerate(candles):
                if not isinstance(candle, dict):
                    continue

                sender_num = candle.get("candle_number", i)
                sender_swing = candle.get("swing_type", "").lower()

                # 1. Identify connection keys from identify_definitions
                # Format: define_2_firstfound_129_in_connection_with_define_1_68
                connection_keys = [k for k in candle.keys() if "_in_connection_with_" in k]
                
                for conn_key in connection_keys:
                    try:
                        # Parse the logic label (identical/opposite) stored as the value in identify_definitions
                        logic_label = candle[conn_key] 
                        
                        # Split key to find the messenger number (last part of the string)
                        parts = conn_key.split('_')
                        messenger_num = int(parts[-1])
                        
                        # 2. INTRUDER CHECK (Liquidity Sweep)
                        messenger_candle = next((c for c in candles if isinstance(c, dict) and c.get("candle_number") == messenger_num), None)
                        
                        if messenger_candle and messenger_candle.get("swept_by_liquidity") is True:
                            intruder_num = messenger_candle.get("swept_by_candle_number")
                            if intruder_num is not None and messenger_num < intruder_num < sender_num:
                                # Construct dynamic key for Intruder
                                intruder_key = f"{conn_key}_{logic_label}_condition_beyond_firstchecked_intruder_number_{intruder_num}"
                                candle[intruder_key] = True

                        # 3. OUTLAW CHECK (Opposite Swing in Range)
                        outlaw_found = None
                        for mid_candle in candles:
                            if not isinstance(mid_candle, dict): continue
                            mid_num = mid_candle.get("candle_number")
                            
                            # Only check candles between the 'firstchecked' (messenger) and current 'sender'
                            if mid_num is not None and messenger_num < mid_num < sender_num:
                                mid_swing = mid_candle.get("swing_type", "").lower()
                                
                                is_outlaw = False
                                if sender_swing == "swing_low" and mid_swing == "swing_high":
                                    is_outlaw = True
                                elif sender_swing == "swing_high" and mid_swing == "swing_low":
                                    is_outlaw = True
                                
                                if is_outlaw:
                                    # Capture the first occurrence
                                    if outlaw_found is None or mid_num < outlaw_found:
                                        outlaw_found = mid_num

                        if outlaw_found is not None:
                            # Construct dynamic key for Outlaw
                            # Example: define_2_firstfound_129_in_connection_with_define_1_68_opposite_condition_beyond_firstchecked_identity_outlaw_number_130
                            outlaw_key = f"{conn_key}_{logic_label}_condition_beyond_firstchecked_identity_outlaw_number_{outlaw_found}"
                            candle[outlaw_key] = True

                    except (ValueError, IndexError):
                        continue

        return processed_data
    
    def add_liquidity_sweepers_to_patterns(target_data_tf, new_key, original_candles):
        """
        Adds sweeper candle details to victim candles in patterns.
        Ensures victim candles have proper sweeper information and adds sweepers to the family.
        Sanitizes sweeper candles to only include essential fields.
        """
        if not isinstance(target_data_tf, dict):
            return

        pattern_key = f"{new_key}_patterns"
        patterns = target_data_tf.get(pattern_key, {})
        
        # Create a map of candle_number to candle for quick lookup from original candles
        # This contains the complete, marked-up candle data with sweeper information
        original_candle_map = {
            c.get("candle_number"): c 
            for c in original_candles 
            if isinstance(c, dict) and "candle_number" in c
        }

        # Define the allowed fields for sanitized sweeper candles
        allowed_sweeper_fields = {
            "open", "high", "low", "close", "volume", "spread", "real_volume",
            "symbol", "time", "candle_number", "timeframe",
            "candle_x", "candle_y", "candle_width", "candle_height",
            "candle_left", "candle_right", "candle_top", "candle_bottom",
            "swing_type", "is_swing", "active_color",
            "draw_x", "draw_y", "draw_w", "draw_h",
            "draw_left", "draw_right", "draw_top", "draw_bottom",
            "is_liquidity_sweep", "swept_victims", "swept_victim_number", "liquidity_price"
        }

        for p_name, family in patterns.items():
            if not isinstance(family, list):
                continue
                
            # Track victims we've already processed and sweepers we've added
            processed_victims = set()
            added_sweepers = set()
            
            # Create a new list to rebuild the family with updated victims and added sweepers
            new_family = []
            
            # First pass: Process all candles, updating victims with their sweeper info
            for candle in family:
                if not isinstance(candle, dict):
                    new_family.append(candle)
                    continue
                
                candle_num = candle.get("candle_number")
                if candle_num is None:
                    new_family.append(candle)
                    continue
                
                # Get the original candle data which has the liquidity sweep markings
                original_candle = original_candle_map.get(candle_num)
                
                if original_candle:
                    # Create a copy to avoid modifying the original
                    updated_candle = candle.copy()
                    
                    # Update the candle with liquidity sweep information from original
                    # This ensures victims have swept_by_liquidity, swept_by_candle_number, etc.
                    if original_candle.get("swept_by_liquidity"):
                        updated_candle["swept_by_liquidity"] = True
                        updated_candle["swept_by_candle_number"] = original_candle.get("swept_by_candle_number")
                        updated_candle["swept_by_candles"] = original_candle.get("swept_by_candles", [])
                        
                        # Mark as victim for processing
                        if candle_num not in processed_victims:
                            processed_victims.add(candle_num)
                    
                    # If this candle itself is a sweeper, update its sweeper info
                    if original_candle.get("is_liquidity_sweep"):
                        updated_candle["is_liquidity_sweep"] = True
                        updated_candle["swept_victims"] = original_candle.get("swept_victims", [])
                        updated_candle["swept_victim_number"] = original_candle.get("swept_victim_number")
                        updated_candle["liquidity_price"] = original_candle.get("liquidity_price")
                    
                    new_family.append(updated_candle)
                else:
                    # If no original data, keep as is
                    new_family.append(candle)
            
            # Second pass: Add missing sweeper candles that aren't already in the family
            for victim_num in processed_victims:
                # Find the victim in new_family to get its sweeper info
                victim_candle = None
                for candle in new_family:
                    if isinstance(candle, dict) and candle.get("candle_number") == victim_num:
                        victim_candle = candle
                        break
                
                if not victim_candle:
                    continue
                
                # Get sweeper candle number(s) from victim
                sweeper_nums = victim_candle.get("swept_by_candles", [])
                if not sweeper_nums:
                    # Try single sweeper number
                    sweeper_num = victim_candle.get("swept_by_candle_number")
                    if sweeper_num:
                        sweeper_nums = [sweeper_num]
                
                for sweeper_num in sweeper_nums:
                    # Check if sweeper is already in family
                    sweeper_exists = False
                    for candle in new_family:
                        if isinstance(candle, dict) and candle.get("candle_number") == sweeper_num:
                            sweeper_exists = True
                            break
                    
                    # If sweeper not in family and not already added, add it
                    if not sweeper_exists and sweeper_num not in added_sweepers:
                        # Find sweeper in original candles
                        original_sweeper = original_candle_map.get(sweeper_num)
                        if original_sweeper:
                            # Create sanitized sweeper copy
                            sweeper_copy = {}
                            for field in allowed_sweeper_fields:
                                if field in original_sweeper:
                                    sweeper_copy[field] = original_sweeper.get(field)
                            
                            # Ensure sweeper is properly marked
                            sweeper_copy["is_liquidity_sweep"] = True
                            sweeper_copy["swept_victim_number"] = victim_num
                            
                            # Add to new_family
                            new_family.append(sweeper_copy)
                            added_sweepers.add(sweeper_num)
            
            # Replace the old family with the new one
            if len(new_family) > len(family) or processed_victims:
                patterns[p_name] = new_family
        
        return target_data_tf
    
    def liquidity_flags_to_sweepers(target_data_tf, patterns_key, identify_config):
        """
        Adds define_{value}_liquidity: true flags to sweeper candles based on define candles they swept.
        
        This function should be called BEFORE draw_definition_tools to ensure sweepers have
        the liquidity flags properly set before drawing.
        
        Args:
            target_data_tf: The timeframe data dictionary containing patterns
            patterns_key: The key for the patterns in target_data_tf (e.g., "new_key_patterns")
            identify_config: Configuration containing define settings
        
        Returns:
            bool: True if any flags were added, False otherwise
        """
        if not identify_config or not target_data_tf:
            return False
        
        patterns = target_data_tf.get(patterns_key, {})
        flags_added = False
        
        #print(f"ADDING LIQUIDITY FLAGS TO SWEEPERS for {patterns_key}")
        
        for family_name, family in patterns.items():
            if not isinstance(family, list):
                continue
            
            # First, build maps of sweepers and their victims
            sweeper_by_number = {}  # {sweeper_candle_number: sweeper_candle}
            sweeper_for_victim = {}  # {victim_candle_number: sweeper_candle}
            
            # Pass 1: Identify all sweepers and map them to their victims
            for candle in family:
                if not isinstance(candle, dict):
                    continue
                
                candle_num = candle.get("candle_number")
                if candle_num is None:
                    continue
                
                # If this candle is a sweeper
                if candle.get("is_liquidity_sweep") is True:
                    sweeper_by_number[candle_num] = candle
                    
                    # Map this sweeper to all its victims
                    swept_victims = candle.get("swept_victims", [])
                    if swept_victims:
                        for victim_num in swept_victims:
                            sweeper_for_victim[victim_num] = candle
                    
                    # Handle single victim case
                    single_victim = candle.get("swept_victim_number")
                    if single_victim and single_victim not in sweeper_for_victim:
                        sweeper_for_victim[single_victim] = candle
            
            # Pass 2: Find all define candles and add flags to their sweepers
            for candle in family:
                if not isinstance(candle, dict):
                    continue
                
                # Check if this candle is a define (any define_n)
                define_name = None
                for key in candle.keys():
                    if key.startswith("define_") and candle[key] is True:
                        define_name = key
                        break
                
                if not define_name:
                    continue
                
                candle_num = candle.get("candle_number")
                if candle_num is None:
                    continue
                
                # Check account management to see if this define should be processed
                define_settings = identify_config.get(define_name, {})
                if define_settings:
                    drawing_enabled = define_settings.get("enable_drawing", True)
                    if not drawing_enabled:
                        # Skip if drawing is disabled for this define
                        continue
                
                # Find the sweeper for this define candle
                sweeper = None
                
                # Priority 1: Check victim mapping
                if candle_num in sweeper_for_victim:
                    sweeper = sweeper_for_victim[candle_num]
                
                # Priority 2: Check direct swept_by_candle_number
                if not sweeper:
                    swept_by_num = candle.get("swept_by_candle_number")
                    if swept_by_num and swept_by_num in sweeper_by_number:
                        sweeper = sweeper_by_number[swept_by_num]
                
                # If we found a sweeper, add the liquidity flag
                if sweeper:
                    liquidity_flag = f"{define_name}_liquidity"
                    
                    # Check if flag already exists to avoid duplicates
                    if not sweeper.get(liquidity_flag):
                        sweeper[liquidity_flag] = True
                        flags_added = True
                        #print(f"  🏷️ Added '{liquidity_flag}: true' to sweeper candle #{sweeper.get('candle_number')} for define #{candle_num}")
        
        return flags_added
   
    def identify_poi(target_data_tf, new_key, original_candles, poi_config):
        """
        Identifies Point of Interest (Breaker) based strictly on price violation.
        Now uses open price comparison between from_subject and after_subject candles
        to determine hit direction, regardless of swing type.
        Tags anchor candles with 'from': True and 'after': True.
        Hit direction determined by: if after_subject open > from_subject open -> hit_from_above,
        if after_subject open < from_subject open -> hit_from_below.
        """
        if not poi_config or not isinstance(target_data_tf, dict):
            return

        pattern_key = f"{new_key}_patterns"
        patterns = target_data_tf.get(pattern_key, {})
        
        from_sub = poi_config.get("from_subject")  
        after_sub = poi_config.get("after_subject") 
        
        # Only check for the exact values, don't auto-append _liquidity
        from_variants = [from_sub] if from_sub else []
        after_variants = [after_sub] if after_sub else []

        candle_map = {
            c.get("candle_number"): c 
            for c in original_candles 
            if isinstance(c, dict) and "candle_number" in c
        }

        for p_name, family in patterns.items():
            # 1. Locate the anchor candles - check only the exact values
            from_candle = None
            for variant in from_variants:
                from_candle = next((c for c in family if c.get(variant) is True), None)
                if from_candle:
                    break
            
            after_candle = None
            for variant in after_variants:
                after_candle = next((c for c in family if c.get(variant) is True), None)
                if after_candle:
                    break
            
            if not from_candle or not after_candle:
                continue

            # Tag anchor candles
            from_candle["from"] = True
            after_candle["after"] = True
                    
            after_num = after_candle.get("candle_number")
            
            # Determine target price level from from_candle
            # Check which price key to use from config
            swing_type = from_candle.get("swing_type", "").lower()
            
            if "high" in swing_type:
                price_key = poi_config.get("subject_is_swinghigh_or_lowerhigh", "low")
            else:
                price_key = poi_config.get("subject_is_swinglow_or_higherlow", "high")

            clean_key = price_key.replace("_price", "") 
            target_price = from_candle.get(clean_key)
            
            if target_price is None:
                continue

            # Determine hit direction based on open price comparison
            from_open = from_candle.get("open")
            after_open = after_candle.get("open")
            
            # Default values
            hit_from_above = False
            hit_from_below = False
            
            if from_open is not None and after_open is not None:
                if after_open > from_open:
                    # After subject open is above from subject open -> price came from above to hit below
                    hit_from_above = True
                elif after_open < from_open:
                    # After subject open is below from subject open -> price came from below to hit above
                    hit_from_below = True
                # If equal, both remain False (neutral/direct hit)

            hitler_record = None

            # Search for the violator candle after 'after_subject'
            for oc in original_candles:
                if not isinstance(oc, dict) or oc.get("candle_number") <= after_num:
                    continue
                    
                # Check for price violation based on swing type
                if swing_type == "swing_low":
                    violator_low = oc.get("low")
                    if violator_low is not None and violator_low < target_price:
                        hitler_record = oc.copy()
                        break
                
                elif swing_type == "swing_high":
                    violator_high = oc.get("high")
                    if violator_high is not None and violator_high > target_price:
                        hitler_record = oc.copy()
                        break
                
                else:
                    continue

            if hitler_record:
                h_num = hitler_record.get("candle_number")
                direction_label = "below" if swing_type == "swing_low" else "above"
                
                # Attach direction flags to hitler candle (determined by open price comparison)
                hitler_record["hit_from_above"] = hit_from_above
                hitler_record["hit_from_below"] = hit_from_below
                
                label = f"after_subject_{after_sub}_violator_{h_num}_breaks_{direction_label}_{from_sub}_{clean_key}_price_{target_price:.5f}"
                
                from_candle[label] = True
                hitler_record["is_hitler_poi"] = True
                hitler_record["point_of_interest"] = True
                
                # Enrich coordinates for visualization
                coordinate_keys = [
                    "candle_x", "candle_y", "candle_width", "candle_height",
                    "candle_left", "candle_right", "candle_top", "candle_bottom"
                ]
                full_record = candle_map.get(h_num)
                if full_record:
                    for k in coordinate_keys:
                        hitler_record[k] = full_record.get(k)
                
                family.append(hitler_record)
                from_candle["pattern_entry"] = True
            else:
                from_candle["pattern_entry"] = True

        return target_data_tf

    def identify_poi_mitigation(target_data_tf, new_key, poi_config):
        """
        Removes patterns where specific candles (restrict_definitions_mitigation) 
        violate the target price based on open price comparison between from_subject and restrict candles.
        Now uses universal method: if restrict candle open > from candle open -> hit_from_above,
        if restrict candle open < from candle open -> hit_from_below.
        No longer relies on swing type for direction assumptions.
        """
        if not poi_config or not isinstance(target_data_tf, dict):
            return

        pattern_key = f"{new_key}_patterns"
        patterns = target_data_tf.get(pattern_key, {})
        from_sub = poi_config.get("from_subject")
        restrict_raw = poi_config.get("restrict_definitions_mitigation")
        
        if not restrict_raw:
            return

        restrict_subs = [s.strip() for s in restrict_raw.split(",")]
        
        # Only check for the exact from_subject value, don't auto-append _liquidity
        from_variants = [from_sub] if from_sub else []
        
        patterns_to_remove = []

        for p_name, family in patterns.items():
            # Find from_candle using exact value only
            from_candle = None
            for variant in from_variants:
                from_candle = next((c for c in family if c.get(variant) is True), None)
                if from_candle:
                    break
                    
            if not from_candle:
                continue

            target_swingtype = from_candle.get("swing_type", "").lower()
            
            # Determine the target price from configuration
            if "high" in target_swingtype:
                price_key = poi_config.get("subject_is_swinghigh_or_lowerhigh", "low")
            else:
                price_key = poi_config.get("subject_is_swinglow_or_higherlow", "high")

            clean_key = price_key.replace("_price", "") 
            target_price = from_candle.get(clean_key)
            
            if target_price is None:
                continue
            
            # Get from_candle open price for comparison
            from_open = from_candle.get("open")

            is_mitigated = False
            
            # Check each restrict subject using exact values only (no auto-appended _liquidity)
            for sub_key in restrict_subs:
                # Only check for the exact subject value
                sub_variants = [sub_key]
                
                restrict_candle = None
                for variant in sub_variants:
                    restrict_candle = next((c for c in family if c.get(variant) is True), None)
                    if restrict_candle:
                        break
                
                if restrict_candle:
                    # Get restrict_candle open price for direction determination
                    restrict_open = restrict_candle.get("open")
                    
                    # Determine hit direction based on open price comparison
                    hit_from_above = False
                    hit_from_below = False
                    
                    if from_open is not None and restrict_open is not None:
                        if restrict_open > from_open:
                            hit_from_above = True
                        elif restrict_open < from_open:
                            hit_from_below = True
                    
                    # Check for price violation based on swing type
                    if target_swingtype == "swing_low":
                        violator_low = restrict_candle.get("low")
                        # If violator_low is < target_price, it's a mitigation
                        if violator_low is not None and violator_low < target_price:
                            # Attach direction flags to restrict candle
                            restrict_candle["hit_from_above"] = hit_from_above
                            restrict_candle["hit_from_below"] = hit_from_below
                            restrict_candle["is_mitigation"] = True
                            is_mitigated = True
                            break
                    
                    elif target_swingtype == "swing_high":
                        violator_high = restrict_candle.get("high")
                        # If violator_high is > target_price, it's a mitigation
                        if violator_high is not None and violator_high > target_price:
                            # Attach direction flags to restrict candle
                            restrict_candle["hit_from_above"] = hit_from_above
                            restrict_candle["hit_from_below"] = hit_from_below
                            restrict_candle["is_mitigation"] = True
                            is_mitigated = True
                            break
                    
                    else:
                        # ("no violator")
                        continue

            if is_mitigated:
                patterns_to_remove.append(p_name)

        # Clean up patterns that hit the mitigation criteria
        for p_name in patterns_to_remove:
            del patterns[p_name]

        return target_data_tf

    def identify_swing_mitigation_between_definitions(target_data_tf, new_key, original_candles, poi_config):
        """
        Checks for swing violations between multiple pairs of definitions (sender and receiver).
        The config expects a comma-separated string: "define_1_define_3, define_4_define_10"
        If any candle between a pair matches the receiver's swing_type and violates the price, 
        the pattern is removed.
        """
        if not poi_config or not isinstance(target_data_tf, dict):
            return

        pattern_key = f"{new_key}_patterns"
        patterns = target_data_tf.get(pattern_key, {})
        from_sub = poi_config.get("from_subject")
        
        # Get the raw string, e.g., "define_1_define_3, define_2_define_4"
        restrict_raw = poi_config.get("restrict_swing_mitigation_between_definitions")
        if not restrict_raw:
            return

        # Split by comma to handle multiple pairs
        restrict_pairs = [p.strip() for p in restrict_raw.split(",") if p.strip()]
        patterns_to_remove = []

        for p_name, family in patterns.items():
            from_candle = next((c for c in family if c.get(from_sub) is True), None)
            if not from_candle:
                continue

            # Determine target price level once per pattern based on from_subject
            target_swingtype = from_candle.get("swing_type", "").lower()
            if "high" in target_swingtype:
                price_key = poi_config.get("subject_is_swinghigh_or_lowerhigh", "low")
            else:
                price_key = poi_config.get("subject_is_swinglow_or_higherlow", "high")

            clean_key = price_key.replace("_price", "")
            target_price = from_candle.get(clean_key)
            
            if target_price is None:
                continue

            is_mitigated = False

            # Evaluate each pair defined in the config
            for pair_str in restrict_pairs:
                parts = pair_str.split("_")
                # Expecting format: define, N, define, M -> 4 parts
                if len(parts) < 4:
                    continue
                
                sender_key = f"{parts[0]}_{parts[1]}"
                receiver_key = f"{parts[2]}_{parts[3]}"

                sender_candle = next((c for c in family if c.get(sender_key) is True), None)
                receiver_candle = next((c for c in family if c.get(receiver_key) is True), None)

                if not sender_candle or not receiver_candle:
                    continue

                s_num = sender_candle.get("candle_number")
                r_num = receiver_candle.get("candle_number")
                receiver_swing_type = receiver_candle.get("swing_type", "").lower()
                
                # Define search range (exclusive)
                start_range = min(s_num, r_num) + 1
                end_range = max(s_num, r_num) - 1

                # Scan range for violations
                for oc in original_candles:
                    if not isinstance(oc, dict):
                        continue
                    
                    c_num = oc.get("candle_number")
                    if start_range <= c_num <= end_range:
                        current_swing = oc.get("swing_type", "").lower()
                        
                        # Match the swing type of the receiver
                        if current_swing == receiver_swing_type:
                            if receiver_swing_type == "swing_low":
                                v_low = oc.get("low")
                                if v_low is not None and v_low < target_price:
                                    is_mitigated = True
                                    break
                            elif receiver_swing_type == "swing_high":
                                v_high = oc.get("high")
                                if v_high is not None and v_high > target_price:
                                    is_mitigated = True
                                    break
                
                if is_mitigated:
                    break # No need to check other pairs for this pattern if one triggered

            if is_mitigated:
                patterns_to_remove.append(p_name)

        # Clean up patterns
        for p_name in patterns_to_remove:
            del patterns[p_name]

        return target_data_tf

    def identify_selected(target_data_tf, new_key, poi_config):
        """
        Filters pattern records based on extreme or non-extreme values of a specific define_n.
        Config format: "multiple_selection": "define_3_extreme" or "define_3_non_extreme"
        """
        if not poi_config or not isinstance(target_data_tf, dict):
            return target_data_tf

        pattern_key = f"{new_key}_patterns"
        patterns = target_data_tf.get(pattern_key, {})
        if not patterns:
            return target_data_tf

        selection_raw = poi_config.get("multiple_selection")
        if not selection_raw:
            return target_data_tf

        # Parse config: e.g., "define_3_extreme" -> target_key="define_3", mode="extreme"
        parts = selection_raw.split("_")
        if len(parts) < 3:
            return target_data_tf

        target_define_key = f"{parts[0]}_{parts[1]}" # e.g., "define_3"
        mode = parts[2].lower() # "extreme" or "non"
        if mode == "non":
            mode = "non_extreme"

        # 1. Collect all patterns containing the target definition and their prices
        eligible_patterns = []
        
        for p_name, family in patterns.items():
            # Find the candle in this pattern that has target_define_key: True
            target_candle = next((c for c in family if c.get(target_define_key) is True), None)
            
            if target_candle:
                swing_type = target_candle.get("swing_type", "").lower()
                # Determine which price to look at based on swing type
                if "high" in swing_type:
                    price = target_candle.get("high")
                else:
                    price = target_candle.get("low")
                
                if price is not None:
                    eligible_patterns.append({
                        "name": p_name,
                        "price": price,
                        "swing_type": swing_type
                    })

        if not eligible_patterns:
            return target_data_tf

        # 2. Determine the winner based on the criteria
        # We assume all patterns for a specific define_n share the same swing_type category 
        # (all highs or all lows) for a meaningful comparison.
        first_swing = eligible_patterns[0]["swing_type"]
        is_high_type = "high" in first_swing
        
        selected_pattern_name = None
        
        if is_high_type:
            # For Higher Highs: 
            # Extreme = Highest High | Non-Extreme = Lowest High
            if mode == "extreme":
                winner = max(eligible_patterns, key=lambda x: x["price"])
            else: # non_extreme
                winner = min(eligible_patterns, key=lambda x: x["price"])
        else:
            # For Lower Lows: 
            # Extreme = Lowest Low | Non-Extreme = Highest Low
            if mode == "extreme":
                winner = min(eligible_patterns, key=lambda x: x["price"])
            else: # non_extreme
                winner = max(eligible_patterns, key=lambda x: x["price"])

        selected_pattern_name = winner["name"]

        # 3. Remove all patterns that were part of this comparison but didn't win
        # Note: Patterns NOT containing the define_n are left untouched.
        patterns_to_remove = [p["name"] for p in eligible_patterns if p["name"] != selected_pattern_name]
        
        for p_name in patterns_to_remove:
            if p_name in patterns:
                del patterns[p_name]

        return target_data_tf

    def identify_candle_after_poi_and_apply_condition(target_data_tf, new_key, original_candles, poi_config, identify_config):
        """
        Validates that the candle(s) after the POI hit meets a condition relative to the entry level.
        Supports three selection types:
        - fixed: Check a specific candle position (N) - must meet condition
        - random: Check N candles after POI, at least one must meet condition
        - sequence: Check N candles after POI, ALL must meet condition
        Adds candle_after_poi flag to the found candle(s) in the pattern family.
        If condition is not met and remove_outlaw is True, the entire pattern record is removed.
        If remove_outlaw is False, patterns that don't meet the condition are kept but not flagged.
        Now includes hit direction tracking to determine if candle is above or below entry.
        """
        if not poi_config or not original_candles:
            return
        
        pattern_key = f"{new_key}_patterns"
        patterns = target_data_tf.get(pattern_key, {})
        
        # Get configuration
        candles_after_config = poi_config.get("candles_after_poi_confirmation", {})
        if not candles_after_config:
            return
        
        selection_type = candles_after_config.get("selection_type", "fixed").lower()
        candle_position = candles_after_config.get("candle_position", 1)  # For fixed: position; For random/sequence: count
        condition_mode = candles_after_config.get("candle_condition", "").lower()  # "behind_entry" or "beyond_entry"
        remove_outlaw = candles_after_config.get("remove_outlaw", False)  # Default to False if not specified
        
        if not condition_mode:
            return
        
        from_sub = poi_config.get("from_subject")
        from_variants = [from_sub] if from_sub else []
        
        # Build candle map for quick lookup
        candle_map = {c.get("candle_number"): c for c in original_candles if isinstance(c, dict) and "candle_number" in c}
        
        # Track patterns to delete (those that don't meet condition) - only if remove_outlaw is True
        patterns_to_delete = []
        
        for p_name, family in list(patterns.items()):
            # Find the entry level candle (from_subject)
            entry_candle = None
            for variant in from_variants:
                entry_candle = next((c for c in family if c.get(variant) is True), None)
                if entry_candle:
                    break
            
            if not entry_candle:
                if remove_outlaw:
                    patterns_to_delete.append(p_name)
                continue
            
            # Find the POI hitler candle in the family
            hitler_candle = next((c for c in family if c.get("is_hitler_poi") is True), None)
            
            if not hitler_candle:
                if remove_outlaw:
                    patterns_to_delete.append(p_name)
                continue
            
            # Get hit direction from the hitler candle
            hit_from_above = hitler_candle.get("hit_from_above", False)
            hit_from_below = hitler_candle.get("hit_from_below", False)
            
            # Get the hitler candle number
            hitler_num = hitler_candle.get("candle_number")
            if hitler_num is None:
                if remove_outlaw:
                    patterns_to_delete.append(p_name)
                continue
            
            # Get entry level prices and swing type
            entry_type = entry_candle.get("swing_type", "").lower()
            
            # Determine which price to use from entry level based on config
            if "high" in entry_type:
                price_key = poi_config.get("subject_is_swinghigh_or_lowerhigh", "low")
            else:
                price_key = poi_config.get("subject_is_swinglow_or_higherlow", "high")
            
            clean_key = price_key.replace("_price", "")
            entry_price = entry_candle.get(clean_key)
            
            if entry_price is None:
                if remove_outlaw:
                    patterns_to_delete.append(p_name)
                continue
            
            # Determine which candles to check based on selection type
            candles_to_check = []
            
            if selection_type == "fixed":
                # Check only the specific candle position
                target_candle_num = hitler_num + candle_position
                target_candle = candle_map.get(target_candle_num)
                if target_candle:
                    candles_to_check = [(target_candle_num, target_candle)]
            
            elif selection_type == "random":
                # Check all candles from position 1 to N
                for pos in range(1, candle_position + 1):
                    target_candle_num = hitler_num + pos
                    target_candle = candle_map.get(target_candle_num)
                    if target_candle:
                        candles_to_check.append((target_candle_num, target_candle))
            
            elif selection_type == "sequence":
                # Check all candles from position 1 to N (must all meet condition)
                for pos in range(1, candle_position + 1):
                    target_candle_num = hitler_num + pos
                    target_candle = candle_map.get(target_candle_num)
                    if target_candle:
                        candles_to_check.append((target_candle_num, target_candle))
                    else:
                        # Missing candle breaks the sequence
                        candles_to_check = []
                        break
            
            else:
                # Default to fixed behavior
                selection_type = "fixed"
                target_candle_num = hitler_num + candle_position
                target_candle = candle_map.get(target_candle_num)
                if target_candle:
                    candles_to_check = [(target_candle_num, target_candle)]
            
            if not candles_to_check:
                if remove_outlaw:
                    patterns_to_delete.append(p_name)
                continue
            
            # Function to check if a candle meets the condition
            def check_condition(target_candle, target_candle_num, entry_price, entry_type, condition_mode):
                target_high = target_candle.get("high")
                target_low = target_candle.get("low")
                
                if target_high is None or target_low is None:
                    return False, None, None
                
                # Determine if candle after POI is above or below entry level
                candle_above_entry = False
                candle_below_entry = False
                
                # Check if the entire candle is above the entry level
                if target_low > entry_price:
                    candle_above_entry = True
                # Check if the entire candle is below the entry level
                elif target_high < entry_price:
                    candle_below_entry = True
                # If candle straddles the entry level, check where most of the candle is relative to entry
                else:
                    # Calculate midpoint of candle to determine bias
                    candle_mid = (target_high + target_low) / 2
                    if candle_mid > entry_price:
                        candle_above_entry = True
                    else:
                        candle_below_entry = True
                
                # Apply the condition logic
                condition_met = False
                mode = "behind" if "behind" in condition_mode else "beyond"
                
                if mode == "behind":
                    if "high" in entry_type:  # Entry is swing_high
                        condition_met = (target_low > entry_price) or (target_high < entry_price)
                    elif "low" in entry_type:  # Entry is swing_low
                        condition_met = (target_high < entry_price) or (target_low > entry_price)
                
                elif mode == "beyond":
                    if "high" in entry_type:  # Entry is swing_high
                        condition_met = (target_high > entry_price) or (target_low < entry_price)
                    elif "low" in entry_type:  # Entry is swing_low
                        condition_met = (target_low < entry_price) or (target_high > entry_price)
                
                return condition_met, candle_above_entry, candle_below_entry
            
            # Check candles based on selection type
            condition_met_overall = False
            candles_to_add = []
            
            if selection_type == "fixed":
                # Single candle must meet condition
                target_candle_num, target_candle = candles_to_check[0]
                condition_met, candle_above_entry, candle_below_entry = check_condition(
                    target_candle, target_candle_num, entry_price, entry_type, condition_mode
                )
                
                if condition_met:
                    condition_met_overall = True
                    candles_to_add.append((target_candle_num, target_candle, candle_above_entry, candle_below_entry))
            
            elif selection_type == "random":
                # At least one candle must meet condition
                for target_candle_num, target_candle in candles_to_check:
                    condition_met, candle_above_entry, candle_below_entry = check_condition(
                        target_candle, target_candle_num, entry_price, entry_type, condition_mode
                    )
                    
                    if condition_met:
                        condition_met_overall = True
                        candles_to_add.append((target_candle_num, target_candle, candle_above_entry, candle_below_entry))
                        break  # Found one, stop checking
            
            elif selection_type == "sequence":
                # ALL candles must meet condition
                all_met = True
                temp_candles_to_add = []
                
                for target_candle_num, target_candle in candles_to_check:
                    condition_met, candle_above_entry, candle_below_entry = check_condition(
                        target_candle, target_candle_num, entry_price, entry_type, condition_mode
                    )
                    
                    if condition_met:
                        temp_candles_to_add.append((target_candle_num, target_candle, candle_above_entry, candle_below_entry))
                    else:
                        all_met = False
                        break
                
                if all_met and temp_candles_to_add:
                    condition_met_overall = True
                    candles_to_add = temp_candles_to_add
            
            # If condition is NOT met and remove_outlaw is True, mark pattern for deletion
            if not condition_met_overall:
                if remove_outlaw:
                    patterns_to_delete.append(p_name)
                continue
            
            # If condition is met, add the candle(s) to the family with flags
            for target_candle_num, target_candle, candle_above_entry, candle_below_entry in candles_to_add:
                # Create a copy to avoid modifying original
                candle_copy = target_candle.copy()
                candle_copy["candle_after_poi"] = True
                candle_copy[f"candle_after_poi_position_{target_candle_num - hitler_num}"] = True
                candle_copy[f"candle_after_poi_condition_{condition_mode}"] = True
                candle_copy[f"candle_after_poi_selection_type_{selection_type}"] = True
                
                # Add hit direction and position relative to entry level
                if hit_from_above:
                    candle_copy["hit_from_above_poi"] = True
                    if candle_above_entry:
                        candle_copy["candle_after_poi_above_entry"] = True
                    elif candle_below_entry:
                        candle_copy["candle_after_poi_below_entry"] = True
                
                elif hit_from_below:
                    candle_copy["hit_from_below_poi"] = True
                    if candle_above_entry:
                        candle_copy["candle_after_poi_above_entry"] = True
                    elif candle_below_entry:
                        candle_copy["candle_after_poi_below_entry"] = True
                
                else:
                    # Neutral hit (direct hit without clear direction)
                    candle_copy["hit_from_neutral_poi"] = True
                    if candle_above_entry:
                        candle_copy["candle_after_poi_above_entry"] = True
                    elif candle_below_entry:
                        candle_copy["candle_after_poi_below_entry"] = True
                
                # Also mark whether the candle after POI continued in the same direction as the hit
                if hit_from_above and candle_below_entry:
                    candle_copy["continued_direction_after_poi"] = True
                    candle_copy["poi_continued_downward"] = True
                elif hit_from_below and candle_above_entry:
                    candle_copy["continued_direction_after_poi"] = True
                    candle_copy["poi_continued_upward"] = True
                
                # Add to family
                family.append(candle_copy)
            
            # Also mark on entry candle that condition was met with hit direction context
            entry_candle[f"candle_after_poi_condition_met_{candle_position}_{condition_mode}_{selection_type}"] = True
            entry_candle[f"candle_after_poi_hit_direction_{'above' if hit_from_above else 'below' if hit_from_below else 'neutral'}"] = True
            
            # Mark the selection type and count on entry candle
            entry_candle[f"candle_after_poi_selection_type_{selection_type}_count_{candle_position}"] = True
            entry_candle[f"candle_after_poi_candles_checked_{len(candles_to_check)}"] = True
            
            # Mark above/below based on the first candle found
            first_candle_above = candles_to_add[0][2] if candles_to_add else False
            first_candle_below = candles_to_add[0][3] if candles_to_add else False
            
            if first_candle_above:
                entry_candle[f"candle_after_poi_above_entry_{candle_position}"] = True
            elif first_candle_below:
                entry_candle[f"candle_after_poi_below_entry_{candle_position}"] = True
        
        # Remove patterns that didn't meet the condition (only if remove_outlaw is True)
        if remove_outlaw:
            for p_name in patterns_to_delete:
                if p_name in patterns:
                    del patterns[p_name]

    def validate_contour_maker_position(target_data_tf, new_key, original_candles, poi_config):
        """
        Validates that the contour maker for the 'after' define candle exists BEFORE the Hitler candle
        and is NOT the Hitler candle itself.
        
        For patterns with 'after' defined, this function checks:
        1. If the 'after' candle has a contour_maker
        2. If the contour_maker candle number is BEFORE the Hitler candle number
        3. If the contour_maker is NOT the Hitler candle itself
        
        IMPORTANT: This validation only applies to patterns with a Hitler candle
        (is_hitler_poi or point_of_interest). Patterns with pending_entry_level: true
        are skipped entirely from this validation.
        
        If any of these conditions fail, the pattern is removed.
        
        Args:
            target_data_tf: The timeframe data containing patterns
            new_key: The key for the current pattern
            original_candles: The full original candle data
            poi_config: The POI configuration containing 'after_subject'
        
        Returns:
            target_data_tf: The modified timeframe data with invalid patterns removed
        """
        if not poi_config or not isinstance(target_data_tf, dict):
            return target_data_tf

        pattern_key = f"{new_key}_patterns"
        patterns = target_data_tf.get(pattern_key, {})
        
        if not patterns:
            return target_data_tf

        after_sub = poi_config.get("after_subject")
        if not after_sub:
            return target_data_tf

        # Only check for the exact after_subject value
        after_variants = [after_sub] if after_sub else []
        
        patterns_to_remove = []

        for p_name, family in patterns.items():
            if not isinstance(family, list):
                continue

            # Find the 'after' candle using exact value
            after_candle = None
            for variant in after_variants:
                after_candle = next((c for c in family if c.get(variant) is True), None)
                if after_candle:
                    break

            if not after_candle:
                # If no after candle found, skip this pattern (it might be invalid already)
                continue

            # Find the Hitler candle in the family
            hitler_candle = next(
                (c for c in family if c.get("is_hitler_poi") is True or c.get("point_of_interest") is True),
                None
            )

            if not hitler_candle:
                # If no Hitler candle found, this pattern is invalid - remove it
                patterns_to_remove.append(p_name)
                continue

            # CRITICAL CHECK: If this pattern has pending_entry_level, skip validation entirely
            # Check if any candle in the family has pending_entry_level: true
            has_pending_entry = any(c.get("pending_entry_level") is True for c in family)
            
            if has_pending_entry:
                # Skip all validation for pending entry patterns
                continue

            # Get the contour_maker from the after candle
            contour_maker = after_candle.get("contour_maker")
            
            if not contour_maker:
                # No contour maker found - pattern is invalid by definition
                patterns_to_remove.append(p_name)
                continue

            # Get contour maker candle number
            contour_candle_num = contour_maker.get("candle_number")
            hitler_candle_num = hitler_candle.get("candle_number")
            after_candle_num = after_candle.get("candle_number")

            # Validate we have all needed numbers
            if contour_candle_num is None or hitler_candle_num is None:
                patterns_to_remove.append(p_name)
                continue

            # Condition 1: Contour maker MUST NOT be the Hitler candle itself
            if contour_candle_num == hitler_candle_num:
                # The contour maker IS the Hitler candle - invalid pattern
                patterns_to_remove.append(p_name)
                continue

            # Condition 2: Contour maker MUST be BEFORE the Hitler candle
            # (candle_number smaller means earlier in time)
            if contour_candle_num > hitler_candle_num:
                # Contour maker appears after Hitler candle - invalid pattern
                patterns_to_remove.append(p_name)
                continue

            # Condition 3: Also check that the contour maker is not the after candle itself
            # (contour maker and after candle can be different)
            if contour_candle_num == after_candle_num:
                # This would mean the after candle IS the contour maker, which is fine
                # as long as it's before the Hitler candle (already checked above)
                pass

            # If we get here, all conditions are met - pattern is valid

        # Remove all invalid patterns
        for p_name in patterns_to_remove:
            if p_name in patterns:
                del patterns[p_name]

        return target_data_tf

    def remove_outlawed_swings_in_between_definitions(target_data_tf, new_key, original_candles, poi_config):
        """
        Removes patterns that have ANY swing type between the specific define_1 and define_2
        candles found in the pattern family.
        
        This function finds the define_1 candle (with 'from': True) and define_2 candle 
        (with 'after': True) in the pattern, then checks the FULL original candle data
        for any swings between their candle numbers.
        
        Config format:
            "remove_outlawed_swings_in_between_definitions": "define_1_define_2, define_2_define_3"
        
        Args:
            target_data_tf: The timeframe data containing patterns
            new_key: The key for the current pattern
            original_candles: The full original candle data
            poi_config: The POI configuration containing the setting
        
        Returns:
            target_data_tf: The modified timeframe data with outlaw patterns removed
        """
        if not poi_config or not isinstance(target_data_tf, dict) or not original_candles:
            return target_data_tf

        # Get the configuration
        remove_config = poi_config.get("remove_outlawed_swings_in_between_definitions", "")
        if not remove_config:
            return target_data_tf

        pattern_key = f"{new_key}_patterns"
        patterns = target_data_tf.get(pattern_key, {})
        if not patterns:
            return target_data_tf

        # Parse the configuration
        pairs = [p.strip() for p in remove_config.split(",") if p.strip()]
        if not pairs:
            return target_data_tf

        # Build a lookup dictionary of original candles by candle_number
        original_candle_lookup = {}
        for candle in original_candles:
            if isinstance(candle, dict) and candle.get("candle_number") is not None:
                original_candle_lookup[candle["candle_number"]] = candle

        # Track patterns to remove
        patterns_to_remove = []

        # Process each pattern family
        for p_name, family in patterns.items():
            if not isinstance(family, list):
                continue

            # Check each pair configuration
            for pair in pairs:
                parts = pair.split("_")
                if len(parts) < 4:
                    continue
                    
                def1_key = f"{parts[0]}_{parts[1]}"  # e.g., "define_1"
                def2_key = f"{parts[2]}_{parts[3]}"  # e.g., "define_2"

                # Find the define_1 candle (with 'from': True) and define_2 candle (with 'after': True)
                from_candle = None  # This is the define_1 candle
                after_candle = None  # This is the define_2 candle
                
                for candle in family:
                    if isinstance(candle, dict):
                        # The define_1 candle has 'from': True
                        if candle.get("from") is True and candle.get(def1_key) is True:
                            from_candle = candle
                        # The define_2 candle has 'after': True
                        if candle.get("after") is True and candle.get(def2_key) is True:
                            after_candle = candle

                # If we can't find both, skip this pattern
                if not from_candle or not after_candle:
                    continue

                # Get candle numbers
                from_num = from_candle.get("candle_number")
                after_num = after_candle.get("candle_number")
                
                if from_num is None or after_num is None:
                    continue

                # Determine the range between the two definitions
                start = min(from_num, after_num) + 1
                end = max(from_num, after_num) - 1

                # If there are no candles between them, skip
                if start > end:
                    continue

                # Check if there are ANY swing candles between them in the FULL original data
                has_swing_between = False
                
                for candle_num in range(start, end + 1):
                    original_candle = original_candle_lookup.get(candle_num)
                    if not original_candle:
                        continue
                    
                    # Check if this candle has a swing_type (meaning it's a swing candle)
                    swing_type = original_candle.get("swing_type", "").lower()
                    if swing_type and swing_type in ["swing_high", "swing_low"]:
                        has_swing_between = True
                        break

                # If ANY swing exists between the definitions, mark this pattern for removal
                if has_swing_between:
                    patterns_to_remove.append(p_name)
                    break  # No need to check other pairs for this pattern

        # Remove all marked patterns
        for p_name in patterns_to_remove:
            if p_name in patterns:
                del patterns[p_name]
                

        return target_data_tf

    def draw_poi_tools(img, target_data_tf, new_key, poi_config):
        """
        Draws visual markers on the image. 
        Boxes feature a single-edge border on the 'sensitive' price level.
        Updates 'from_candle' with flags regarding its extension or break status.
        Now attaches the formatted time of the breaker candle to the center of boxes.
        Now respects the exact from_subject value without auto-appending _liquidity.
        Skips drawing duplicate POIs that stop at the same Hitler candle.
        Skips drawing duplicate POIs that start from the same from_candle.
        Deletes skipped patterns entirely from the data structure.
        """
        if not poi_config or img is None:
            return img

        pattern_key = f"{new_key}_patterns"
        patterns = target_data_tf.get(pattern_key, {})
        
        drawing_tool = poi_config.get("drawing_tool", "horizontal_line")
        from_sub = poi_config.get("from_subject")
        
        # FIX: Only check for the exact value provided, don't auto-append _liquidity
        from_variants = [from_sub] if from_sub else []
        
        # Config mapping for sensitive edge
        hh_lh_edge = poi_config.get("subject_is_swinghigh_or_lowerhigh") # e.g., "low_price"
        ll_hl_edge = poi_config.get("subject_is_swinglow_or_higherlow")   # e.g., "high_price"
        
        img_height, img_width = img.shape[:2]
        
        # Track which Hitler candles have already been drawn
        drawn_hitler_candles = set()
        # Track which from_candles have already been processed
        drawn_from_candles = set()
        
        # Create a list to store pattern names that should be deleted
        patterns_to_delete = []

        for p_name, family in patterns.items():
            # 1. Identify the origin (from_candle) using exact value only
            from_candle = None
            from_candle_key = None
            
            for variant in from_variants:
                from_candle = next((c for c in family if c.get(variant) is True), None)
                if from_candle:
                    # Create a unique key for this from_candle using its candle number
                    from_candle_num = from_candle.get("candle_number", "unknown")
                    from_candle_key = f"from_{from_candle_num}"
                    break
                    
            if not from_candle:
                # If no from_candle found, delete this pattern
                patterns_to_delete.append(p_name)
                continue
            
            # Check if we've already drawn from this from_candle
            if from_candle_key in drawn_from_candles:
                # Mark as duplicate and delete this pattern
                from_candle["skipped_duplicate_from_candle"] = True
                patterns_to_delete.append(p_name)
                continue
            
            # Mark this from_candle as drawn
            drawn_from_candles.add(from_candle_key)

            # Locate the breaker candle using the boolean flags
            breaker_candle = next((c for c in family if c.get("is_hitler_poi") or c.get("is_invalid_hitler") or c.get("point_of_interest")), None)
            
            # If there's a breaker candle, check if we've already drawn a POI for this Hitler candle
            if breaker_candle:
                hitler_num = breaker_candle.get("candle_number", "unknown")
                
                # Create a unique key for this Hitler candle
                hitler_key = f"hitler_{hitler_num}"
                
                # If we've already drawn a POI for this Hitler candle, delete this pattern
                if hitler_key in drawn_hitler_candles:
                    # Mark as duplicate to avoid processing
                    from_candle["skipped_duplicate_poi"] = True
                    patterns_to_delete.append(p_name)
                    continue
                
                # Mark this Hitler candle as drawn
                drawn_hitler_candles.add(hitler_key)
            
            # 2. Determine X boundaries and Update Flags
            start_x = int(from_candle.get("draw_right", from_candle.get("candle_right", 0)))
            
            formatted_date = ""
            if breaker_candle:
                end_x = int(breaker_candle.get("draw_left", breaker_candle.get("candle_left", img_width)))
                color = (0, 0, 255)  # Red for broken
                
                # FIX: Get the candle_number from the breaker record to avoid "unknown"
                hitler_num = breaker_candle.get("candle_number", "unknown")
                
                # Update the status flags on the origin candle
                from_candle[f"drawn_and_stopped_on_hitler{hitler_num}"] = True
                

                # --- DATE FORMATTING LOGIC ---
                raw_time = breaker_candle.get("time", "")
                try:
                    # Convert "2026-02-13 19:00:00" -> "Feb 13, 2026"
                    dt_obj = datetime.strptime(raw_time, "%Y-%m-%d %H:%M:%S")
                    formatted_date = dt_obj.strftime("%b %d, %Y")
                except (ValueError, TypeError):
                    formatted_date = ""

            else:
                end_x = img_width
                color = (0, 255, 0)  # Green for active
                from_candle["pending_entry_level"] = True

            # 3. Handle Drawing Tools
            
            # --- TOOL: BOX ---
            if "box" in drawing_tool:
                y_high = int(from_candle.get("draw_top", 0))
                y_low = int(from_candle.get("draw_bottom", 0))
                
                # Draw Transparent Fill
                black_color = (0, 0, 0) 
                overlay = img.copy()
                cv2.rectangle(overlay, (start_x, y_high), (end_x, y_low), black_color, -1)
                cv2.addWeighted(overlay, 0.15, img, 0.85, 0, img)

                # --- TEXT DRAWING (Box Center) ---
                if formatted_date:
                    font = cv2.FONT_HERSHEY_SIMPLEX
                    font_scale = 0.4
                    thickness = 1
                    # Calculate text size to offset for true centering
                    text_size = cv2.getTextSize(formatted_date, font, font_scale, thickness)[0]
                    
                    text_x = start_x + (end_x - start_x) // 2 - text_size[0] // 2
                    text_y = y_high + (y_low - y_high) // 2 + text_size[1] // 2
                    
                    cv2.putText(img, formatted_date, (text_x, text_y), font, font_scale, black_color, thickness, cv2.LINE_AA)

                # Determine Sensitive Border logic
                swing_type = from_candle.get("swing_type", "").lower()
                border_y = None

                if "swing_high" in swing_type or "lower_high" in swing_type:
                    border_y = y_low if hh_lh_edge == "low_price" else y_high
                elif "swing_low" in swing_type or "higher_low" in swing_type:
                    border_y = y_high if ll_hl_edge == "high_price" else y_low

                # Draw the single sensitive border line
                if border_y is not None:
                    cv2.line(img, (start_x, border_y), (end_x, border_y), black_color, 1)

            # --- TOOL: DASHED HORIZONTAL LINE ---
            elif "dashed_horizontal_line" in drawing_tool:
                swing_type = from_candle.get("swing_type", "").lower()
                if "high" in swing_type:
                    target_y = int(from_candle.get("draw_top", 0))
                else:
                    target_y = int(from_candle.get("draw_bottom", 0))

                dash_length, gap_length = 10, 5
                curr_x = start_x
                while curr_x < end_x:
                    next_x = min(curr_x + dash_length, end_x)
                    cv2.line(img, (curr_x, target_y), (next_x, target_y), color, 2)
                    curr_x += dash_length + gap_length

            # --- TOOL: STANDARD HORIZONTAL LINE ---
            elif "horizontal_line" in drawing_tool:
                swing_type = from_candle.get("swing_type", "").lower()
                target_y = int(from_candle.get("draw_top", 0)) if "high" in swing_type else int(from_candle.get("draw_bottom", 0))
                cv2.line(img, (start_x, target_y), (end_x, target_y), color, 2)

        # Delete all patterns that were marked for deletion
        for p_name in patterns_to_delete:
            if p_name in patterns:
                del patterns[p_name]

        return img

    def draw_definition_tools(img, target_data_tf, pattern_key, identify_config):
        """
        Draws visual markers for definitions as HORIZONTAL LINES with optional text labels.
        If swept: draws horizontal line from define candle's price level across to sweeper candle
        If not swept: draws horizontal line from define candle extending to the right edge
        
        Now checks account management configuration to determine if drawing is enabled for each define_n.
        Supports both solid and dashed lines based on drawing_tool setting.
        Adds centered text labels above/below the line based on swing type, but ONLY for swept lines.
        """
        if not identify_config or img is None:
            return img
        
        patterns = target_data_tf.get(pattern_key, {})
        img_height, img_width = img.shape[:2]
        
        #print(f"DRAWING DEFINITION TOOLS for {pattern_key}")
        
        total_families = 0
        total_defines = 0
        swept_count = 0
        unswept_count = 0
        skipped_count = 0
        disabled_count = 0
        text_drawn_count = 0
        
        for family_name, family in patterns.items():
            if not isinstance(family, list):
                #print(f"  ⚠️ Family '{family_name}' is not a list, skipping")
                continue
            
            total_families += 1
            #print(f"\n  📁 Family: {family_name} ({len(family)} candles)")
            
            # First, build a map of sweeper candles by their candle_number for easy lookup
            sweeper_by_number = {}  # {sweeper_candle_number: sweeper_candle}
            
            # Also build a map of which sweepers map to which victims
            # This is based on the sweeper's swept_victims field
            sweeper_for_victim = {}  # {victim_candle_number: sweeper_candle}
            
            for candle in family:
                if not isinstance(candle, dict):
                    continue
                
                candle_num = candle.get("candle_number")
                if candle_num is None:
                    continue
                
                # If this candle is a sweeper (has is_liquidity_sweep = True)
                if candle.get("is_liquidity_sweep") is True:
                    sweeper_by_number[candle_num] = candle
                    
                    # Map this sweeper to all its victims
                    swept_victims = candle.get("swept_victims", [])
                    if swept_victims:
                        for victim_num in swept_victims:
                            sweeper_for_victim[victim_num] = candle
                    # Also handle single victim case
                    single_victim = candle.get("swept_victim_number")
                    if single_victim and single_victim not in sweeper_for_victim:
                        sweeper_for_victim[single_victim] = candle
            
            # Now draw for each define candle
            family_defines = 0
            family_swept = 0
            family_unswept = 0
            family_disabled = 0
            family_text_drawn = 0
            
            for candle in family:
                if not isinstance(candle, dict):
                    continue
                
                # Check if this candle is a define (any define_n)
                define_name = None
                for key in candle.keys():
                    if key.startswith("define_") and candle[key] is True:
                        define_name = key
                        break
                
                if not define_name:
                    continue
                
                family_defines += 1
                total_defines += 1
                
                # Get candle details
                candle_num = candle.get("candle_number", "???")
                swing_type = candle.get("swing_type", "").lower()
                
                #print(f"\n    🔍 Processing {define_name} (Candle #{candle_num})")
                #print(f"       Swing type: {swing_type}")
                
                # --- ACCOUNT MANAGEMENT CHECK ---
                # Check if this specific define_n is enabled for drawing
                # First check define-specific settings in identify_config
                define_settings = identify_config.get(define_name, {})
                
                # If define-specific settings exist, check if drawing is enabled
                if define_settings:
                    drawing_enabled = define_settings.get("enable_drawing", True)  # Default to True if not specified
                    #print(f"       📋 Account management for {define_name}: enable_drawing = {drawing_enabled}")
                    
                    if not drawing_enabled:
                        #print(f"       ⏭️ Skipped: {define_name} drawing disabled in account management")
                        disabled_count += 1
                        family_disabled += 1
                        continue
                    
                    # Get text label if available
                    text_label = define_settings.get("text", "")
                    #print(f"       📝 Text label: '{text_label}'")
                else:
                    # No specific settings for this define_n, assume drawing is enabled
                    #print(f"       ℹ️ No account management settings for {define_name}, using default (enabled)")
                    text_label = ""  # No text label by default
                
                # Get drawing tool preference for this specific define
                drawing_tool = define_settings.get("tool", identify_config.get("drawing_tool", "horizontal_line"))
                #print(f"       🖌️ Drawing tool: {drawing_tool}")
                
                # Check all possible swept indicators
                swept_by_num = candle.get("swept_by_candle_number")
                swept_by_liquidity = candle.get("swept_by_liquidity")
                
                # Check if this candle is a victim (has a sweeper mapped to it)
                is_victim = candle_num in sweeper_for_victim
                
                #print(f"       swept_by_candle_number: {swept_by_num}")
                #print(f"       swept_by_liquidity: {swept_by_liquidity}")
                #print(f"       is_victim (has sweeper mapped): {is_victim}")
                
                # Determine the Y-coordinate (price level) based on swing type
                # This is the horizontal line level
                if "swing_high" in swing_type:
                    # For higher high, draw from the HIGH of the candle
                    line_y = int(candle.get("draw_top", candle.get("candle_top", 0)))
                    line_desc = f"high at Y={line_y}"
                    # Start from the RIGHT side of the candle
                    start_x = int(candle.get("draw_right", candle.get("candle_right", 0)))
                    text_position = "above"  # Text should be above the line for higher high
                elif "swing_low" in swing_type:
                    # For lower low, draw from the LOW of the candle
                    line_y = int(candle.get("draw_bottom", candle.get("candle_bottom", img_height)))
                    line_desc = f"low at Y={line_y}"
                    # Start from the RIGHT side of the candle
                    start_x = int(candle.get("draw_right", candle.get("candle_right", 0)))
                    text_position = "below"  # Text should be below the line for lower low
                else:
                    #print(f"        Skipped: Unknown swing type '{swing_type}'")
                    skipped_count += 1
                    continue
                
                #print(f"       Horizontal line level: {line_desc}")
                #print(f"       Start X: {start_x}")
                #print(f"       Text position: {text_position}")
                
                # Determine if swept and find sweeper
                sweeper = None
                end_x = img_width  # Default to right edge
                end_desc = "right edge"
                is_swept = False
                
                # Priority 1: Check if this candle has a sweeper mapped to it via sweeper_for_victim
                if candle_num in sweeper_for_victim:
                    sweeper = sweeper_for_victim[candle_num]
                    sweeper_num = sweeper.get("candle_number", "???")
                    #print(f"       ✅ Swept via victim mapping to sweeper #{sweeper_num}")
                    is_swept = True
                
                # Priority 2: Check direct swept_by_candle_number that exists in sweeper_by_number
                elif swept_by_num and swept_by_num in sweeper_by_number:
                    sweeper = sweeper_by_number[swept_by_num]
                    #print(f"       ✅ Swept via direct swept_by_candle_number={swept_by_num}")
                    is_swept = True
                
                if sweeper:
                    # If swept, draw horizontal line to the sweeper candle's LEFT side
                    sweeper_num = sweeper.get("candle_number", "???")
                    
                    # Get the sweeper's left side coordinate
                    # For sweepers, we want to draw to their left side (where they start)
                    end_x = int(sweeper.get("draw_left", sweeper.get("candle_left", img_width)))
                    
                    # Make sure we're drawing to the LEFT of the sweeper (earlier in time)
                    # If the sweeper is to the left of the victim (shouldn't happen by logic), adjust
                    if end_x < start_x:
                        # Sweeper is to the left, draw to its right side instead
                        end_x = int(sweeper.get("draw_right", sweeper.get("candle_right", img_width)))
                        end_desc = f"sweeper #{sweeper_num} right side at X={end_x}"
                    else:
                        end_desc = f"sweeper #{sweeper_num} left side at X={end_x}"
                    
                    #print(f"       📍 Swept: drawing horizontal line to {end_desc}")
                    swept_count += 1
                    family_swept += 1
                else:
                    # If not swept, draw horizontal line to right edge
                    #print(f"       ➡️ Not swept: drawing horizontal line to right edge at X={end_x}")
                    unswept_count += 1
                    family_unswept += 1
                
                # Draw the line based on drawing tool preference
                if "dashed_horizontal_line" in drawing_tool:
                    # Draw DASHED horizontal line
                    dash_length = 10
                    gap_length = 5
                    curr_x = start_x
                    
                    while curr_x < end_x:
                        next_x = min(curr_x + dash_length, end_x)
                        cv2.line(img, (curr_x, line_y), (next_x, line_y), (0, 0, 0), 1, cv2.LINE_AA)
                        curr_x += dash_length + gap_length
                    
                    #print(f"       🖍️ Drew DASHED line from X={start_x} to X={end_x}")
                else:
                    # Draw SOLID horizontal line (default)
                    cv2.line(img, (start_x, line_y), (end_x, line_y), (0, 0, 0), 1, cv2.LINE_AA)
                    #print(f"       🖍️ Drew SOLID line from X={start_x} to X={end_x}")
                
                # Draw text label ONLY if the line is swept (has a sweeper)
                if text_label and is_swept:
                    # Calculate center X coordinate of the line
                    center_x = (start_x + end_x) // 2
                    
                    # Calculate Y coordinate based on text position
                    if text_position == "above":
                        # Place text above the line (5 pixels above)
                        text_y = line_y - 5
                        text_bg_y1 = text_y - 15
                        text_bg_y2 = text_y + 5
                    else:  # below
                        # Place text below the line (15 pixels below to account for text height)
                        text_y = line_y + 15
                        text_bg_y1 = text_y - 15
                        text_bg_y2 = text_y + 5
                    
                    # Get text size
                    font = cv2.FONT_HERSHEY_SIMPLEX
                    font_scale = 0.4
                    thickness = 1
                    (text_width, text_height), baseline = cv2.getTextSize(text_label, font, font_scale, thickness)
                    
                    # Calculate text position to center it horizontally
                    text_x = center_x - (text_width // 2)
                    
                    # Draw white background rectangle for better readability
                    padding = 2
                    bg_x1 = text_x - padding
                    bg_y1 = text_y - text_height - padding
                    bg_x2 = text_x + text_width + padding
                    bg_y2 = text_y + padding
                    
                    # Ensure background stays within image bounds
                    bg_x1 = max(0, bg_x1)
                    bg_y1 = max(0, bg_y1)
                    bg_x2 = min(img_width, bg_x2)
                    bg_y2 = min(img_height, bg_y2)
                    
                    # Draw background rectangle
                    cv2.rectangle(img, (bg_x1, bg_y1), (bg_x2, bg_y2), (255, 255, 255), -1)
                    
                    # Draw text in black
                    cv2.putText(img, text_label, (text_x, text_y), font, font_scale, (0, 0, 0), thickness, cv2.LINE_AA)
                    
                    #print(f"       📝 Drew text '{text_label}' at center X={center_x}, Y={text_y} ({text_position} line)")
                    text_drawn_count += 1
                    family_text_drawn += 1
        return img
    
    def identify_pending_prices(target_data_tf, new_key, record_config, dev_base_path, new_folder_name):
        """
        Saves limit orders into a pending_orders folder INSIDE the specific new_filename folder.
        Path: dev_base_path/new_folder_name/pending_orders/limit_orders.json
        Also adds order_type flag to the entry candle in the original data structure
        Also checks poi_entry.json for existing POI orders and adds POI flags to matching patterns
        Also filters out orders where order_type doesn't match poi_entry_order_type
        """
        if not record_config:
            return

        pattern_key = f"{new_key}_patterns"
        patterns = target_data_tf.get(pattern_key, {})
        
        # Load POI entries if they exist
        poi_orders = []
        poi_file = os.path.join(dev_base_path, new_folder_name, "pending_orders", "poi_entry.json")
        if os.path.exists(poi_file):
            try:
                with open(poi_file, 'r', encoding='utf-8') as f:
                    poi_orders = json.load(f)
            except:
                poi_orders = []
        
        # Create a lookup dictionary for POI orders by hitler_time
        poi_by_time = {}
        for poi in poi_orders:
            hitler_time = poi.get("hitler_time")
            if hitler_time:
                poi_by_time[hitler_time] = poi
        
        pending_list = []
        price_map = {
            "low_price": "low",
            "high_price": "high",
            "open_price": "open",
            "close_price": "close"
        }
        
        # Updated Path Logic: Inside the new_folder_name directory
        orders_dir = os.path.join(dev_base_path, new_folder_name, "pending_orders")
        os.makedirs(orders_dir, exist_ok=True)
        orders_file = os.path.join(orders_dir, "limit_orders.json")

        for p_name, family in patterns.items():
            origin_candle = next((c for c in family if c.get("pending_entry_level") is True), None)
            
            # Check if this pattern has a POI origin time matching any POI order
            found_poi = None
            poi_origin_time = None
            pattern_time_id_with_poi = None
            poi_entry_order_type = None
            
            # Scan all candles in the family to find poi_origin_time and POI-related fields
            for candle in family:
                if candle.get("poi_origin_time"):
                    poi_origin_time = candle.get("poi_origin_time")
                    # Check if this poi_origin_time exists in our POI orders
                    if poi_origin_time in poi_by_time:
                        found_poi = poi_by_time[poi_origin_time]
                        # Don't break - continue scanning to get all POI fields
                
                # Check for pattern_time_id_with_poi directly
                if candle.get("pattern_time_id_with_poi") and not pattern_time_id_with_poi:
                    pattern_time_id_with_poi = candle.get("pattern_time_id_with_poi")
                
                # Check for poi_entry_order_type directly
                if candle.get("poi_entry_order_type") and not poi_entry_order_type:
                    poi_entry_order_type = candle.get("poi_entry_order_type")
            
            # First determine the order type for this pattern
            if origin_candle:
                order_data = {
                    "symbol": origin_candle.get("symbol", "unknown"),
                    "timeframe": origin_candle.get("timeframe", "unknown"),
                    "risk_reward": record_config.get("risk_reward", 0),
                    "order_type": "unknown",
                    "entry": 0,
                    "exit": 0,
                    "target": 0
                }

                # Add pattern_time_id_with_poi if it exists
                if pattern_time_id_with_poi:
                    order_data["pattern_time_id_with_poi"] = pattern_time_id_with_poi
                elif poi_origin_time:
                    # Fallback to using poi_origin_time if pattern_time_id_with_poi not found
                    order_data["pattern_time_id_with_poi"] = poi_origin_time
                
                # Add poi_entry_order_type if it exists
                if poi_entry_order_type:
                    order_data["poi_entry_order_type"] = poi_entry_order_type
                elif found_poi:
                    # Fallback to using found_poi order_type
                    order_data["poi_entry_order_type"] = found_poi.get("order_type", "unknown")

                for role in ["entry", "exit", "target"]:
                    role_cfg = record_config.get(role, {})
                    subject_key = role_cfg.get("subject")
                    
                    if subject_key:
                        target_candle = next((c for c in family if c.get(subject_key) is True), None)
                        if target_candle:
                            swing_type = target_candle.get("swing_type", "").lower()
                            price_attr_raw = ""
                            if "high" in swing_type:
                                price_attr_raw = role_cfg.get("subject_is_swinghigh_or_lowerhigh")
                            elif "low" in swing_type:
                                price_attr_raw = role_cfg.get("subject_is_swinglow_or_higherlow")

                            actual_key = price_map.get(price_attr_raw, price_attr_raw)
                            if actual_key:
                                order_data[role] = target_candle.get(actual_key, 0)
                
                # FIX: Look for pattern_entry directly instead of relying on record_config
                entry_candle = next((c for c in family if c.get("pattern_entry") is True), origin_candle)
                
                e_swing = entry_candle.get("swing_type", "").lower()
                type_cfg = record_config.get("order_type", {})
                
                if "high" in e_swing:
                    # Use direct string fallback if config value is None
                    order_type_val = type_cfg.get("subject_is_swinghigh_or_lowerhigh")
                    pattern_order_type = order_type_val if order_type_val is not None else "sell_limit"
                else:
                    order_type_val = type_cfg.get("subject_is_swinglow_or_higherlow")
                    pattern_order_type = order_type_val if order_type_val is not None else "buy_limit"
                
                order_data["order_type"] = pattern_order_type
                
                # Add order_type flag to the origin candle (pending_entry_level candle)
                origin_candle["order_type"] = pattern_order_type
                
                # Also add order_type flag to the entry candle if it's different from origin_candle
                if entry_candle != origin_candle:
                    entry_candle["order_type"] = pattern_order_type
                
                # If POI found, add POI flags to the candle that has the order_type
                if found_poi and poi_origin_time:
                    # Add POI flags to the entry candle (which already has order_type)
                    entry_candle["poi_entry_order_type"] = found_poi.get("order_type", "unknown")
                    entry_candle["pattern_time_id_with_poi"] = poi_origin_time
                    
                    # Also add to origin candle if it's different
                    if origin_candle != entry_candle:
                        origin_candle["poi_entry_order_type"] = found_poi.get("order_type", "unknown")
                        origin_candle["pattern_time_id_with_poi"] = poi_origin_time

                # ===== NEW FILTERING LOGIC =====
                # Check if order has both order_type and poi_entry_order_type and they must match
                has_both_types = (order_data.get("order_type") != "unknown" and 
                                 order_data.get("poi_entry_order_type") not in [None, "unknown"])
                
                if has_both_types:
                    # If both exist, they must match - otherwise skip this order
                    if order_data["order_type"] != order_data["poi_entry_order_type"]:
                        continue  # Skip adding this order to pending_list
                
                # If order has only order_type (no POI), keep it
                # If order has matching types, keep it

                pending_list.append(order_data)

        if pending_list:
            existing_orders = []
            if os.path.exists(orders_file):
                try:
                    with open(orders_file, 'r', encoding='utf-8') as f:
                        existing_orders = json.load(f)
                except: 
                    existing_orders = []

            existing_orders.extend(pending_list)
            with open(orders_file, 'w', encoding='utf-8') as f:
                json.dump(existing_orders, f, indent=4)

    def identify_hitler_prices(target_data_tf, new_key, record_config, dev_base_path, new_folder_name, target_data_full=None):
        """
        Saves hitler/POI entry information into a poi_entry.json file.
        Path: dev_base_path/new_folder_name/pending_orders/poi_entry.json
        Follows the same logic as identify_prices but targets Hitler/POI candles
        Only records orders for symbols that have confirmation keys across all timeframes
        Also adds order_type flag to the Hitler/POI candle in the original data structure
        """
        if not record_config:
            return

        pattern_key = f"{new_key}_patterns"
        patterns = target_data_tf.get(pattern_key, {})
        
        pending_poi_list = []
        price_map = {
            "low_price": "low",
            "high_price": "high",
            "open_price": "open",
            "close_price": "close"
        }
        
        # Updated Path Logic: Inside the new_folder_name directory
        orders_dir = os.path.join(dev_base_path, new_folder_name, "pending_orders")
        os.makedirs(orders_dir, exist_ok=True)
        poi_file = os.path.join(orders_dir, "poi_entry.json")

        # Check if this source timeframe has any confirmation keys in ANY timeframe of the full target data
        has_confirmation = False
        source_tf = None
        
        # First, determine the source timeframe from any pattern
        for p_name, family in patterns.items():
            if family and len(family) > 0:
                source_tf = family[0].get("timeframe")
                if source_tf:
                    break
        
        if source_tf and target_data_full:
            # Check through ALL timeframes in the full target data
            for tf_key, tf_data in target_data_full.items():
                if isinstance(tf_data, dict):
                    # Check each key in this timeframe's data
                    for data_key in tf_data.keys():
                        if isinstance(data_key, str) and f"_confirmation_from_{source_tf}_poi_" in data_key:
                            has_confirmation = True
                            break
                if has_confirmation:
                    break
        
        # If no confirmation keys found across all timeframes, don't record any orders
        if not has_confirmation:
            return

        for p_name, family in patterns.items():
            # Find the Hitler/POI candle instead of pending_entry_level
            hitler_candle = next((c for c in family if c.get("is_hitler_poi") is True or c.get("point_of_interest") is True), None)
            
            if hitler_candle:
                # Get the hitler time for this candle
                hitler_time = hitler_candle.get("time", "")
                
                poi_data = {
                    "symbol": hitler_candle.get("symbol", "unknown"),
                    "timeframe": hitler_candle.get("timeframe", "unknown"),
                    "risk_reward": record_config.get("risk_reward", 0),
                    "order_type": "unknown",
                    "entry": 0,
                    "exit": 0,
                    "target": 0,
                    "hitler_time": hitler_time  # Additional field for hitler time
                }

                # Get entry, exit, and target prices using the same logic as identify_prices
                for role in ["entry", "exit", "target"]:
                    role_cfg = record_config.get(role, {})
                    subject_key = role_cfg.get("subject")
                    
                    if subject_key:
                        target_candle = next((c for c in family if c.get(subject_key) is True), None)
                        if target_candle:
                            swing_type = target_candle.get("swing_type", "").lower()
                            price_attr_raw = ""
                            if "high" in swing_type:
                                price_attr_raw = role_cfg.get("subject_is_swinghigh_or_lowerhigh")
                            elif "low" in swing_type:
                                price_attr_raw = role_cfg.get("subject_is_swinglow_or_higherlow")

                            actual_key = price_map.get(price_attr_raw, price_attr_raw)
                            if actual_key:
                                poi_data[role] = target_candle.get(actual_key, 0)
                
                # FIX: Look for pattern_entry directly instead of relying on record_config
                entry_candle = next((c for c in family if c.get("pattern_entry") is True), hitler_candle)
                
                e_swing = entry_candle.get("swing_type", "").lower()
                type_cfg = record_config.get("order_type", {})
                
                if "high" in e_swing:
                    # Use direct string fallback if config value is None
                    order_type_val = type_cfg.get("subject_is_swinghigh_or_lowerhigh")
                    poi_data["order_type"] = order_type_val if order_type_val is not None else "sell_limit"
                else:
                    order_type_val = type_cfg.get("subject_is_swinglow_or_higherlow")
                    poi_data["order_type"] = order_type_val if order_type_val is not None else "buy_limit"
                
                # Add order_type flag to the Hitler/POI candle
                hitler_candle["order_type"] = poi_data["order_type"]
                
                # Also add order_type flag to the entry candle if it's different from hitler_candle
                if entry_candle != hitler_candle:
                    entry_candle["order_type"] = poi_data["order_type"]

                pending_poi_list.append(poi_data)

        if pending_poi_list:
            # Instead of overwriting, we should append/merge with existing data
            # But we need to ensure we don't have duplicates
            existing_poi = []
            if os.path.exists(poi_file):
                try:
                    with open(poi_file, 'r', encoding='utf-8') as f:
                        existing_poi = json.load(f)
                except: 
                    existing_poi = []
            
            # Create a dictionary keyed by (symbol, timeframe, hitler_time) to avoid duplicates
            poi_dict = {}
            
            # Add existing entries to dictionary
            for entry in existing_poi:
                key = (entry.get("symbol"), entry.get("timeframe"), entry.get("hitler_time"))
                poi_dict[key] = entry
            
            # Add new entries (will overwrite if same key exists)
            for entry in pending_poi_list:
                key = (entry.get("symbol"), entry.get("timeframe"), entry.get("hitler_time"))
                poi_dict[key] = entry
            
            # Convert back to list
            merged_poi = list(poi_dict.values())
            
            with open(poi_file, 'w', encoding='utf-8') as f:
                json.dump(merged_poi, f, indent=4)

    def candle_after_poi_pending_order_modification(dev_base_path, new_folder_name, poi_config, target_data=None, symbol=None):
        """
        Modifies existing limit orders in pending_orders folder based on switch_order_type configuration.
        ONLY modifies orders if a candle after POI exists in the pattern for that order's timeframe.
        Reads the current limit_orders.json, checks each order against the switch rules,
        and modifies order_type if conditions match AND candle_after_poi exists.
        """
        if not poi_config:
            return
        
        # Get the switch_order_type configuration from poi's candles_after_poi_confirmation
        candles_after_config = poi_config.get("candles_after_poi_confirmation", {})
        switch_rules = candles_after_config.get("switch_order_type", {})
        
        if not switch_rules:
            return
        
        # Path to the pending orders file
        orders_dir = os.path.join(dev_base_path, new_folder_name, "pending_orders")
        orders_file = os.path.join(orders_dir, "limit_orders.json")
        
        if not os.path.exists(orders_file):
            return
        
        # Load existing orders
        try:
            with open(orders_file, 'r', encoding='utf-8') as f:
                orders = json.load(f)
        except Exception:
            return
        
        if not orders:
            return
        
        # Track modifications
        modifications_made = 0
        
        # Process each order against the switch rules
        for order in orders:
            current_order_type = order.get("order_type", "")
            order_symbol = order.get("symbol", "")
            order_timeframe = order.get("timeframe", "")
            
            # Check if candle after POI exists for this order's symbol and timeframe
            candle_after_poi_exists = False
            
            if target_data is not None and symbol is not None:
                # If target_data and symbol were passed, we can check directly
                if symbol == order_symbol:
                    # Look through the target_data for patterns with candle_after_poi
                    for tf, tf_content in target_data.items():
                        if tf == order_timeframe and isinstance(tf_content, dict):
                            for key, value in tf_content.items():
                                if key.endswith("_patterns") and isinstance(value, list):
                                    # Check each pattern in the family
                                    for pattern in value:
                                        if isinstance(pattern, dict) and pattern.get("candle_after_poi") is True:
                                            candle_after_poi_exists = True
                                            break
                                    if candle_after_poi_exists:
                                        break
                        if candle_after_poi_exists:
                            break
            else:
                # Fallback: Check the symbol's config.json file directly
                symbol_config_path = os.path.join(dev_base_path, new_folder_name, order_symbol, "config.json")
                if os.path.exists(symbol_config_path):
                    try:
                        with open(symbol_config_path, 'r', encoding='utf-8') as f:
                            sym_data = json.load(f)
                        
                        # Look through all timeframes and patterns for candle_after_poi
                        for tf, tf_content in sym_data.items():
                            if tf == order_timeframe and isinstance(tf_content, dict):
                                for key, value in tf_content.items():
                                    if key.endswith("_patterns") and isinstance(value, list):
                                        for pattern in value:
                                            if isinstance(pattern, dict) and pattern.get("candle_after_poi") is True:
                                                candle_after_poi_exists = True
                                                break
                                        if candle_after_poi_exists:
                                            break
                            if candle_after_poi_exists:
                                break
                    except Exception:
                        pass
            
            # If no candle after POI exists, skip this order
            if not candle_after_poi_exists:
                continue
            
            # Check each rule in switch_order_type (supports any key names)
            for rule_key, rule_config in switch_rules.items():
                if not isinstance(rule_config, dict):
                    continue
                
                existing_type = rule_config.get("if_existing_is", "")
                switch_to_type = rule_config.get("switch_to", "")
                
                # Skip if either value is empty
                if not existing_type or not switch_to_type:
                    continue
                
                # Check if current order type matches the rule
                if current_order_type == existing_type:
                    order["order_type"] = switch_to_type
                    modifications_made += 1
                    break  # Once a rule matches, stop checking other rules for this order
        
        # Save the modified orders back to file if any changes were made
        if modifications_made > 0:
            try:
                with open(orders_file, 'w', encoding='utf-8') as f:
                    json.dump(orders, f, indent=4)
            except Exception:
                pass

    def poi_order_direction_validation(target_data_tf, pattern_key):
        """
        Validates patterns based on order_type and poi_entry_order_type.
        Rules:
        1. If a pattern has no order_type field at all, it's invalid and removed immediately
        2. If a pattern has both order_type and poi_entry_order_type, they must match
        3. Only patterns that satisfy these conditions remain
        
        Args:
            target_data_tf: The timeframe data dictionary containing patterns
            pattern_key: The key for the patterns dictionary (e.g., "1h_confirmation_from_4h_poi_primary_patterns")
        
        Returns:
            bool: True if any patterns were removed, False otherwise
        """
        if pattern_key not in target_data_tf:
            return False
        
        patterns_dict = target_data_tf[pattern_key]
        if not isinstance(patterns_dict, dict):
            return False
        
        patterns_removed = False
        patterns_to_delete = []
        
        # Iterate through each pattern in the patterns dictionary
        for pattern_name, pattern_candles in patterns_dict.items():
            if not isinstance(pattern_candles, list):
                patterns_to_delete.append(pattern_name)
                patterns_removed = True
                log(f"    🗑️ Removing invalid pattern {pattern_name} - not a list")
                continue
            
            # Track if we've found order_type and poi_entry_order_type in this pattern
            has_order_type = False
            has_poi_order_type = False
            found_order_type = None
            found_poi_order_type = None
            
            # Check each candle in the pattern family
            for candle in pattern_candles:
                # Check for order_type field
                if "order_type" in candle:
                    has_order_type = True
                    found_order_type = candle["order_type"]
                
                # Check for poi_entry_order_type field
                if "poi_entry_order_type" in candle:
                    has_poi_order_type = True
                    found_poi_order_type = candle["poi_entry_order_type"]
            
            # RULE 1: If pattern has no order_type field at all, remove it immediately
            if not has_order_type:
                patterns_to_delete.append(pattern_name)
                patterns_removed = True
                continue
            
            # RULE 2: If pattern has both order_type and poi_entry_order_type, they must match
            if has_order_type and has_poi_order_type:
                if found_order_type != found_poi_order_type:
                    patterns_to_delete.append(pattern_name)
                    patterns_removed = True
                    continue
            
            # RULE 3: If pattern has order_type but no poi_entry_order_type, keep it
            # (this is a valid pattern that just doesn't have POI confirmation)
            
            # RULE 4: If pattern has order_type and matching poi_entry_order_type, keep it
        
        # Delete all invalid patterns
        for pattern_name in patterns_to_delete:
            del patterns_dict[pattern_name]
        
        # If patterns dictionary is now empty, remove the entire patterns key
        if not patterns_dict:
            del target_data_tf[pattern_key]
        
        return patterns_removed

    def limit_orders_old_record_cleanup(dev_base_path, new_folder_name):
        """
        Deletes the limit_orders.json file inside the specific new_filename folder 
        to ensure a fresh start for that entry's synchronization.
        """
        orders_file = os.path.join(dev_base_path, new_folder_name, "pending_orders", "limit_orders.json")
        if os.path.exists(orders_file):
            try:
                os.remove(orders_file)
            except Exception as e:
                log(f"Could not clear limit orders for {new_folder_name}: {e}")

    def identify_paused_symbols(target_data, dev_base_path, new_folder_name):
        """
        Synchronizes all limit orders with their pattern anchors (from/after) 
        and saves them to paused_symbols.json without overwriting previous symbols.
        """
        orders_file = os.path.join(dev_base_path, new_folder_name, "pending_orders", "limit_orders.json")
        paused_folder = os.path.join(dev_base_path, new_folder_name, "paused_symbols_folder")
        paused_file = os.path.join(paused_folder, "paused_symbols.json")

        if not os.path.exists(orders_file):
            return

        try:
            with open(orders_file, 'r', encoding='utf-8') as f:
                active_orders = json.load(f)
        except Exception as e:
            log(f"Error reading limit orders: {e}")
            return

        # Load existing paused records to append to them, or start fresh if it's the first symbol
        all_paused_records = []
        if os.path.exists(paused_file):
            try:
                with open(paused_file, 'r', encoding='utf-8') as f:
                    all_paused_records = json.load(f)
            except:
                all_paused_records = []

        # Create a lookup set of (symbol, timeframe, time) to avoid duplicate entries in paused_symbols
        existing_keys = {(r.get("symbol"), r.get("timeframe"), r.get("time")) for r in all_paused_records}

        new_records_found = False

        for order in active_orders:
            order_sym = order.get("symbol")
            order_tf = order.get("timeframe")
            order_entry = order.get("entry")
            
            # Access the specific timeframe data
            tf_data = target_data.get(order_tf, {})
            
            for key, value in tf_data.items():
                if key.endswith("_patterns"):
                    for p_name, family in value.items():
                        from_c = next((c for c in family if c.get("from") is True), None)
                        after_c = next((c for c in family if c.get("after") is True), None)

                        # MATCHING LOGIC: 
                        # 1. Symbol matches
                        # 2. This specific "from" candle hasn't been added yet
                        if from_c and after_c and from_c.get("symbol") == order_sym:
                            # We use time as a unique identifier for the pattern start
                            pattern_time = from_c.get("time")
                            
                            if (order_sym, order_tf, pattern_time) not in existing_keys:
                                # Create record with full order details
                                record = {
                                    "from": True,
                                    "symbol": order_sym,
                                    "timeframe": order_tf,
                                    "entry": order_entry,
                                    "order_type": order.get("order_type"),
                                    "time": pattern_time,
                                    "exit": order.get("exit", 0),
                                    "target": order.get("target"),
                                    "tick_size": order.get("tick_size"),
                                    "tick_value": order.get("tick_value"),
                                    "after": {
                                        "after": True,
                                        "time": after_c.get("time")
                                    }
                                }
                                all_paused_records.append(record)
                                existing_keys.add((order_sym, order_tf, pattern_time))
                                new_records_found = True

        # Save the cumulative list back to the file
        if new_records_found:
            os.makedirs(paused_folder, exist_ok=True)
            with open(paused_file, 'w', encoding='utf-8') as f:
                json.dump(all_paused_records, f, indent=4)
    
    def populate_limit_orders_with_paused_orders(dev_base_path, new_folder_name):
        """
        Checks the limit orders file and adds any orders from paused_symbols.json 
        that are missing in the active limit orders.
        
        Args:
            dev_base_path: Base development path
            new_folder_name: Current run folder name
        """
        orders_file = os.path.join(dev_base_path, new_folder_name, "pending_orders", "limit_orders.json")
        paused_folder = os.path.join(dev_base_path, new_folder_name, "paused_symbols_folder")
        paused_file = os.path.join(paused_folder, "paused_symbols.json")
        
        # If no paused symbols file exists, nothing to do
        if not os.path.exists(paused_file):
            return 0
        
        # Load paused symbols/orders
        try:
            with open(paused_file, 'r', encoding='utf-8') as f:
                paused_orders = json.load(f)
        except Exception as e:
            log(f"Error reading paused symbols file: {e}")
            return 0
        
        if not paused_orders:
            return 0
        
        # Load existing active limit orders, or create empty list if file doesn't exist
        active_orders = []
        if os.path.exists(orders_file):
            try:
                with open(orders_file, 'r', encoding='utf-8') as f:
                    active_orders = json.load(f)
            except Exception as e:
                log(f"Error reading limit orders file: {e}")
                active_orders = []
        
        # Create lookup set of existing active orders to identify missing ones
        # Using (symbol, timeframe, entry, time) as unique identifier
        existing_order_keys = set()
        for order in active_orders:
            key = (
                order.get("symbol"),
                order.get("timeframe"),
                order.get("entry"),
                order.get("time")  # pattern time
            )
            existing_order_keys.add(key)
        
        # Track orders to add
        orders_added = 0
        orders_to_add = []
        
        # Check each paused order and add if missing from active orders
        for paused_order in paused_orders:
            # Extract the after time from the nested structure
            after_time = None
            if "after" in paused_order and isinstance(paused_order["after"], dict):
                after_time = paused_order["after"].get("time")
            
            order_key = (
                paused_order.get("symbol"),
                paused_order.get("timeframe"),
                paused_order.get("entry"),
                paused_order.get("time")  # pattern time
            )
            
            # If this order is not in active orders, add it
            if order_key not in existing_order_keys:
                # Create a clean order object from the paused record
                new_order = {
                    "symbol": paused_order.get("symbol"),
                    "timeframe": paused_order.get("timeframe"),
                    "entry": paused_order.get("entry"),
                    "exit": paused_order.get("exit", 0),
                    "order_type": paused_order.get("order_type", "LIMIT"),
                    "target": paused_order.get("target"),
                    "tick_size": paused_order.get("tick_size"),
                    "tick_value": paused_order.get("tick_value"),
                    "time": paused_order.get("time"),  # pattern time
                    "from_paused": True,  # Flag to indicate this was restored from paused
                    "status": "active"
                }
                
                # Add after time if it exists
                if after_time:
                    new_order["after_time"] = after_time
                
                orders_to_add.append(new_order)
                existing_order_keys.add(order_key)  # Prevent duplicates in this run
                orders_added += 1
        
        # If we found missing orders, append them to the active orders and save
        if orders_added > 0:
            # Combine existing orders with new ones
            updated_orders = active_orders + orders_to_add
            
            # Ensure the pending_orders directory exists
            orders_dir = os.path.join(dev_base_path, new_folder_name, "pending_orders")
            os.makedirs(orders_dir, exist_ok=True)
            
            # Save the updated orders file
            try:
                with open(orders_file, 'w', encoding='utf-8') as f:
                    json.dump(updated_orders, f, indent=4)
            except Exception as e:
                log(f"Error writing updated limit orders: {e}")
                return 0
        
        return orders_added           

    def extract_poi_to_confirmation(target_data_tf, new_key, dev_base_path, new_folder_name, sym, pending_full_candle_refs, poi_confirmation_timeframes=None):
        # -----------------------------------------------------------------
        # STRICT VALIDATION: Only proceed if we have confirmation timeframes configured
        # -----------------------------------------------------------------
        if not poi_confirmation_timeframes:
            # No configuration provided - don't create any confirmations
            return target_data_tf
        
        # Check if this key is already a confirmation key
        is_confirmation_key = "_confirmation_from_" in new_key and not new_key.endswith("_patterns")
        
        if is_confirmation_key:
            # This is a confirmation key - we need to parse it to find the source and target
            parts = new_key.split('_confirmation_from_')
            if len(parts) == 2:
                target_tf = parts[0]  # This should match the current timeframe
                remaining = parts[1]
                
                # Split remaining into source_tf and original_key
                source_parts = remaining.split('_poi_')
                if len(source_parts) == 2:
                    source_tf = source_parts[0]
                    original_key = source_parts[1]
                    
                    # Log what we're processing
                    
                    # Now we can use source_tf to check if confirmations are allowed
                    if source_tf not in poi_confirmation_timeframes:
                        return target_data_tf
                    
                    # Check if target_tf is in allowed list for this source_tf
                    allowed_tfs = poi_confirmation_timeframes[source_tf]
                    if target_tf not in allowed_tfs:
                        log(f"    ⏭️ {target_tf} not in allowed confirmations for {source_tf}: {allowed_tfs}")
                        return target_data_tf
                    
                    # Get the actual confirmation data (the candles)
                    confirmation_data = target_data_tf.get(new_key, [])
                    if confirmation_data:
                        log(f"       Found {len(confirmation_data)} candles in confirmation data")
                        
                        # Look for POI markers in the original patterns? Or process differently?
                        # This depends on what you want to do with existing confirmation keys
                        
                        return target_data_tf
        
        # If we get here, this is a regular pattern key (not a confirmation key)
        pattern_key = f"{new_key}_patterns"
        patterns = target_data_tf.get(pattern_key, {})
        
        if not patterns:
            return target_data_tf
        
        # Get the source timeframe from any POI candle
        source_tf = None
        for pattern_name, pattern_candles in patterns.items():
            if pattern_candles and len(pattern_candles) > 0:
                source_tf = pattern_candles[0].get("timeframe")
                if source_tf:
                    break
        
        if not source_tf:
            return target_data_tf
        
        # -----------------------------------------------------------------
        # STRICT FILTERING: Only use confirmation timeframes explicitly defined for this source_tf
        # -----------------------------------------------------------------
        # Check if this source timeframe has any configured confirmation relationships
        if source_tf not in poi_confirmation_timeframes:
            # No configuration for this source timeframe - skip completely
            return target_data_tf
        
        # Get the allowed confirmation timeframes for this source_tf
        allowed_confirmation_tfs = poi_confirmation_timeframes[source_tf]
        
        if not allowed_confirmation_tfs:
            # Empty list means no confirmations for this source_tf
            log(f"    ⏭️ Empty confirmation list for {source_tf} POI - skipping confirmations")
            return target_data_tf
        
        
        # Find all available timeframes from pending_full_candle_refs
        available_tfs = set()
        tf_to_ref_map = {}  # Map timeframe to its reference data
        for ref_key, ref_data in pending_full_candle_refs.items():
            if ref_key.startswith('full_candles_ref_') or '_full_candles_ref_' in ref_key:
                tf = ref_data["tf"]
                available_tfs.add(tf)
                tf_to_ref_map[tf] = ref_data
        
        # Filter allowed confirmation timeframes to only those that are available
        lower_tfs = []
        for tf in allowed_confirmation_tfs:
            if tf in available_tfs:
                lower_tfs.append(tf)
        
        if not lower_tfs:
            return target_data_tf
        
        # Collect all POI timestamps from source timeframe
        poi_timestamps = set()
        poi_candles = []  # Store the actual POI candles for reference
        
        for pattern_name, pattern_candles in patterns.items():
            for candle in pattern_candles:
                if candle.get("point_of_interest") is True:
                    timestamp = candle.get("time")
                    if timestamp:
                        poi_timestamps.add(timestamp)
                        poi_candles.append(candle)
        
        if not poi_timestamps:
            return target_data_tf
        
        log(f"  🔍 Found {len(poi_timestamps)} POI candles in {source_tf} for {sym}")
        
        any_confirmations_created = False
        
        # For each POI timestamp, look for it in each allowed lower timeframe
        for timestamp in sorted(list(poi_timestamps)):
            log(f"    📍 Processing POI at {timestamp}")
            
            # Find matching POI candle for metadata
            source_poi_candle = next((p for p in poi_candles if p.get("time") == timestamp), None)
            
            # For each lower timeframe, try to find the candle
            for lower_tf in lower_tfs:
                # Get the reference data for this timeframe
                ref_data = tf_to_ref_map.get(lower_tf)
                if not ref_data:
                    continue
                    
                # The candles are stored in target_data_tf under the config_key
                lower_tf_candles = ref_data["target_data_ref"].get(ref_data["config_key"], [])
                
                if not lower_tf_candles:
                    log(f"      ⚠️ No candle data found for {lower_tf}")
                    continue
                
                # Find the index of this timestamp in lower timeframe candles
                poi_index = -1
                for i, candle in enumerate(lower_tf_candles):
                    if candle.get("time") == timestamp:
                        poi_index = i
                        break
                
                if poi_index == -1:
                    #log(f"      ⚠️ Timestamp {timestamp} not found in {lower_tf}")
                    continue
                
                any_confirmations_created = True
                
                # Extract from this index to the end (latest)
                candles_from_poi = lower_tf_candles[poi_index:]
                
                # Mark which POI these candles belong to
                for candle in candles_from_poi:
                    candle["poi_origin_time"] = timestamp
                    candle["poi_origin_tf"] = source_tf
                    if source_poi_candle:
                        candle["poi_origin_pattern"] = source_poi_candle.get("swing_type", "unknown")
                        # Copy important POI attributes
                        for attr in ["point_of_interest", "swing_type", "swing_high", "swing_low"]:
                            if attr in source_poi_candle:
                                candle[f"source_poi_{attr}"] = source_poi_candle.get(attr)
                
                # Create the confirmation key in the format: {lower_tf}_confirmation_from_{source_tf}_poi_{original_key}
                # Remove the new_folder_name prefix from new_key to get original
                original_key = new_key.replace(f"{new_folder_name}_", "", 1) if new_key.startswith(f"{new_folder_name}_") else new_key
                confirmation_key = f"{lower_tf}_confirmation_from_{source_tf}_poi_{original_key}"
                
                # Add or append to existing data for this confirmation key
                if confirmation_key not in target_data_tf:
                    target_data_tf[confirmation_key] = []
                
                # Add unique candles (avoid duplicates)
                existing_times = {c.get("time") for c in target_data_tf[confirmation_key]}
                new_candles = [c for c in candles_from_poi if c.get("time") not in existing_times]
                target_data_tf[confirmation_key].extend(new_candles)
                
                # Sort by time
                target_data_tf[confirmation_key].sort(key=lambda x: x.get("time", ""))
        
        if not any_confirmations_created:
            log(f"    ℹ️ No confirmation candles could be created for {source_tf} POI timestamps")
        
        return target_data_tf

    def generate_confirmation_charts(dev_base_path, new_folder_name, sym, target_sym_dir, target_data, pending_full_candle_data, tfs_to_keep=None, poi_confirmation_timeframes=None):
        """
        Generates brand new charts for confirmation data extracted from POI candles.
        Creates charts directly from the confirmation candle data without needing source charts.
        Features dynamic width scaling for optimal candle visibility.
        Records pixel coordinates for each candle in the target_data structure.
        
        Chart filename format: {lower_tf}_confirmation_from_{source_tf}_poi.png
        
        Args:
            dev_base_path: Base path to developers folder
            new_folder_name: The entry folder name
            sym: Symbol being processed
            target_sym_dir: Target symbol directory
            target_data: The complete target data dictionary (all timeframes)
            pending_full_candle_data: Dictionary of queued full candle data for ALL timeframes
            tfs_to_keep: Optional list of timeframes to process
            poi_confirmation_timeframes: Dictionary defining allowed POI -> confirmation timeframe relationships
                                        Format: {"source_tf": ["confirmation_tf1", "confirmation_tf2", ...]}
                                        If None, no charts will be generated.
        """
        # -----------------------------------------------------------------
        # STRICT VALIDATION: Only proceed if we have confirmation timeframes configured
        # -----------------------------------------------------------------
        if not poi_confirmation_timeframes:
            # No configuration provided - don't generate any charts
            return
        
        # Determine which timeframes to process
        if tfs_to_keep is None:
            timeframes_to_process = list(target_data.keys())
        else:
            timeframes_to_process = tfs_to_keep
        
        chart_count = 0
        
        # Configuration for readable candles
        MIN_CANDLE_WIDTH = 30  # Minimum pixels per candle for readability
        MAX_CANDLE_WIDTH = 40  # Maximum pixels per candle (prevents extremely wide images)
        MIN_CANDLE_SPACING = 20  # Minimum pixels between candles
        BASE_HEIGHT = 4000  # Fixed height for all charts
        MAX_IMAGE_WIDTH = 90000000  # Maximum width to prevent insane image sizes
        
        # Border and padding configuration
        BORDER_THICKNESS = 1  # Thickness of the border line
        
        # OUTER PADDING (image edge to border)
        OUTER_PADDING_LEFT = 10
        OUTER_PADDING_RIGHT = 10
        OUTER_PADDING_TOP = 70
        OUTER_PADDING_BOTTOM = 70
        
        # INNER PADDING (border to chart area)
        INNER_PADDING_LEFT = 40      # Space from left border to first candle
        INNER_PADDING_RIGHT = 500     # Space from right border to last candle
        INNER_PADDING_TOP = 20       # Space from top border to highest candle
        INNER_PADDING_BOTTOM = 20    # Space from bottom border to lowest candle
        
        # Numbering configuration
        NUMBER_FONT_SCALE = 0  # Smaller font for numbers (set to 0 to disable numbering)
        NUMBER_FONT_THICKNESS = 2
        NUMBER_OFFSET_ABOVE_WICK = 5  # Pixels above the wick to place the number
        NUMBER_BG_PADDING = 2  # Padding around number for background
        
        # Process each timeframe
        for tf in timeframes_to_process:
            if tf not in target_data:
                continue
                
            target_data_tf = target_data[tf]
            
            # Find all confirmation data keys in this timeframe's data (not pattern keys)
            confirmation_keys = []
            for key in target_data_tf.keys():
                if "_confirmation_from_" in key and not key.endswith("_patterns"):
                    confirmation_keys.append(key)
            
            for conf_key in confirmation_keys:
                # Parse the confirmation key to get source and target timeframes
                # Format: {target_tf}_confirmation_from_{source_tf}_poi_{original_key}
                parts = conf_key.split('_confirmation_from_')
                
                if len(parts) != 2:
                    continue
                    
                target_tf = parts[0]  # This is the lower timeframe
                remaining = parts[1]
                
                # Split remaining into source_tf and original_key
                # The remaining part has format: {source_tf}_poi_{original_key}
                source_parts = remaining.split('_poi_')
                if len(source_parts) != 2:
                    continue
                    
                source_tf = source_parts[0]
                original_key = source_parts[1]
                
                if not source_tf or not target_tf:
                    continue
                
                # -----------------------------------------------------------------
                # CRITICAL FILTER: Only generate chart if this relationship is allowed
                # -----------------------------------------------------------------
                # Check if source_tf has any confirmation rules defined
                if source_tf not in poi_confirmation_timeframes:
                    continue
                
                # Get the allowed confirmation timeframes for this source_tf
                allowed_targets = poi_confirmation_timeframes[source_tf]
                
                # Check if target_tf is in the allowed list
                if target_tf not in allowed_targets:
                    log(f"    ⏭️ Skipping chart for {conf_key} - {source_tf}→{target_tf} not in allowed relationships: {allowed_targets}")
                    continue
                
                # Get the confirmation data (this is the actual candle data, not patterns)
                confirmation_data = target_data_tf.get(conf_key, [])
                if not confirmation_data:
                    log(f"    ⚠️ No confirmation data found for {conf_key}")
                    continue
                
                # Log that we're generating chart for this confirmation data
                log(f"    📊 Generating chart for {conf_key} with {len(confirmation_data)} candles")
                
                # Extract OHLC data from confirmation candles, preserving candle_number
                ohlc_data = []
                for item in confirmation_data:
                    # Check if item is a dictionary or a string
                    if isinstance(item, dict):
                        # It's a candle dictionary - proceed normally
                        ohlc_data.append({
                            'time': item.get('time', ''),
                            'open': item.get('open', 0),
                            'high': item.get('high', 0),
                            'low': item.get('low', 0),
                            'close': item.get('close', 0),
                            'candle_number': item.get('candle_number', None),  # Preserve the original candle number
                            'original_candle': item  # Store reference to original candle for updating coordinates
                        })
                    elif isinstance(item, str):
                        # It's a string (possibly just a timestamp) - create a minimal candle
                        timestamp = item
                        log(f"       ⚠️ Warning: Found string instead of candle dict in {conf_key}: {timestamp[:50] if len(timestamp) > 50 else timestamp}")
                        
                        # Create a placeholder candle with just the timestamp
                        ohlc_data.append({
                            'time': timestamp,
                            'open': 0,
                            'high': 0,
                            'low': 0,
                            'close': 0,
                            'candle_number': None,
                            'original_candle': {'time': timestamp}  # Create a minimal original candle
                        })
                    else:
                        # Unknown type - skip
                        log(f"       ⚠️ Warning: Unexpected data type in {conf_key}: {type(item)}")
                        continue
                
                if not ohlc_data:
                    log(f"    ⚠️ No valid OHLC data extracted for {conf_key}")
                    continue
                
                num_candles = len(ohlc_data)
                
                # -----------------------------------------------------------------
                # DYNAMIC WIDTH CALCULATION
                # -----------------------------------------------------------------
                
                # Determine optimal candle width based on number of candles
                if num_candles <= 50:
                    # Few candles - make them larger for better visibility
                    base_candle_width = 15
                    base_spacing_multiplier = 1.8
                elif num_candles <= 200:
                    # Medium number of candles - moderate size
                    base_candle_width = 10
                    base_spacing_multiplier = 1.6
                elif num_candles <= 1000:
                    # Many candles - smaller but still readable
                    base_candle_width = 6
                    base_spacing_multiplier = 1.4
                else:
                    # Very many candles - minimum readable size
                    base_candle_width = MIN_CANDLE_WIDTH
                    base_spacing_multiplier = 1.3
                
                # Apply constraints to candle width
                target_candle_width = max(base_candle_width, MIN_CANDLE_WIDTH)
                target_candle_width = min(target_candle_width, MAX_CANDLE_WIDTH)
                
                # Calculate spacing based on candle width and multiplier
                desired_spacing = target_candle_width * base_spacing_multiplier
                
                # Apply minimum spacing constraint
                actual_spacing = max(desired_spacing, MIN_CANDLE_SPACING)
                
                # Calculate the total width needed for candles (from first candle center to last candle center)
                if num_candles > 1:
                    total_span = actual_spacing * (num_candles - 1)
                else:
                    total_span = target_candle_width * 2  # For single candle, give it some space
                
                # Calculate the total width needed for the chart area (including half candles at edges)
                chart_area_width = total_span + target_candle_width
                
                # Add inner padding to get the bordered area width
                bordered_area_width = chart_area_width + INNER_PADDING_LEFT + INNER_PADDING_RIGHT
                
                # Add outer padding to get total image width
                img_width = int(bordered_area_width + OUTER_PADDING_LEFT + OUTER_PADDING_RIGHT)
                
                # Cap width to prevent insane image sizes
                img_width = min(img_width, MAX_IMAGE_WIDTH)
                
                # If width is less than minimum, use minimum
                min_width = OUTER_PADDING_LEFT + OUTER_PADDING_RIGHT + 1000
                if img_width < min_width:
                    img_width = min_width
                
                # Create the dynamic-sized chart
                chart_img = np.ones((BASE_HEIGHT, img_width, 3), dtype=np.uint8) * 255
                
                # Calculate price range for scaling
                all_prices = []
                for d in ohlc_data:
                    # Only include prices if they're non-zero (placeholders might be zero)
                    if d['high'] > 0 or d['low'] > 0:
                        all_prices.extend([d['high'], d['low']])
                
                # If all prices are zero (all placeholder candles), create a dummy range
                if not all_prices:
                    all_prices = [0, 100]  # Dummy range for display
                    log(f"       ⚠️ Warning: No valid price data in {conf_key}, using dummy range")
                
                min_price = min(all_prices)
                max_price = max(all_prices)
                price_range = max_price - min_price
                
                # Add padding to price range (10% on top and bottom)
                price_padding = price_range * 0.1
                min_price -= price_padding
                max_price += price_padding
                price_range = max_price - min_price
                
                # Border positions using OUTER padding (image edge to border)
                border_left = OUTER_PADDING_LEFT
                border_right = img_width - OUTER_PADDING_RIGHT
                border_top = OUTER_PADDING_TOP
                border_bottom = BASE_HEIGHT - OUTER_PADDING_BOTTOM
                
                # Draw border around the chart area
                cv2.rectangle(chart_img, 
                            (border_left, border_top), 
                            (border_right, border_bottom), 
                            (0, 0, 0), BORDER_THICKNESS)
                
                # Chart area INSIDE the border using INNER padding (border to chart)
                chart_left = border_left + INNER_PADDING_LEFT
                chart_right = border_right - INNER_PADDING_RIGHT
                chart_top = border_top + INNER_PADDING_TOP
                chart_bottom = border_bottom - INNER_PADDING_BOTTOM
                chart_width = chart_right - chart_left
                chart_height = chart_bottom - chart_top
                
                # Calculate where to start drawing candles
                # We want to center the candles in the available chart area
                if num_candles > 1:
                    # Calculate if our pre-calculated spacing fits within the chart area
                    if total_span <= chart_width - target_candle_width:
                        # Candles fit - center them
                        start_x = chart_left + (chart_width - (total_span + target_candle_width)) / 2 + (target_candle_width / 2)
                    else:
                        # Something went wrong with calculations - fallback to left alignment
                        start_x = chart_left + (target_candle_width / 2)
                        log(f"       ⚠️ Warning: Spacing calculation mismatch - using fallback")
                else:
                    # Single candle - center it
                    start_x = chart_left + (chart_width / 2)
                
                # Define price to y conversion function for reuse
                def price_to_y(price):
                    # Handle case where price_range is zero to avoid division by zero
                    if price_range == 0:
                        return chart_bottom - chart_height // 2
                    return chart_bottom - int((price - min_price) / price_range * chart_height)
                
                # Draw each candle with its actual candle number (if enabled) and record coordinates
                for i, candle in enumerate(ohlc_data):
                    # Calculate x position
                    if num_candles > 1:
                        x_center = start_x + (i * actual_spacing)
                    else:
                        x_center = start_x
                    
                    # Determine if bullish or bearish (for placeholder candles, treat as neutral/gray)
                    if candle['close'] == 0 and candle['open'] == 0:
                        # Placeholder candle - use gray
                        color = (128, 128, 128)
                        is_bullish = None
                    else:
                        is_bullish = candle['close'] >= candle['open']
                        # Use default green for bullish, red for bearish
                        color = (0, 150, 0) if is_bullish else (0, 0, 255)
                    
                    # Calculate y positions for all OHLC values
                    open_y = price_to_y(candle['open'])
                    close_y = price_to_y(candle['close'])
                    high_y = price_to_y(candle['high'])
                    low_y = price_to_y(candle['low'])
                    
                    # Calculate candle rectangle coordinates for the body
                    half_width = target_candle_width / 2
                    candle_left_x = int(x_center - half_width)
                    candle_right_x = int(x_center + half_width)
                    
                    # For the body: top is min(open, close), bottom is max(open, close)
                    body_top_y = min(open_y, close_y)
                    body_bottom_y = max(open_y, close_y)
                    
                    # Draw the wick (high-low line) - only if we have valid price data
                    if candle['high'] != 0 or candle['low'] != 0:
                        cv2.line(chart_img, 
                                (int(x_center), high_y), 
                                (int(x_center), low_y), 
                                color, 1)
                    
                    # Draw the candle body - only if we have valid open/close
                    if candle['open'] != 0 or candle['close'] != 0:
                        cv2.rectangle(chart_img,
                                    (candle_left_x, body_top_y),
                                    (candle_right_x, body_bottom_y),
                                    color, -1)
                    
                    # Draw candle number only if NUMBER_FONT_SCALE > 0
                    if NUMBER_FONT_SCALE > 0:
                        # Get the actual candle number from the data
                        candle_number = candle.get('candle_number')
                        
                        # If candle_number exists, use it; otherwise, fall back to sequential numbering
                        if candle_number is not None:
                            number_text = str(candle_number)
                        else:
                            number_text = str(i + 1)  # Fallback to sequential numbering
                            if candle['open'] != 0 or candle['close'] != 0:  # Only warn for real candles
                                log(f"       ⚠️ Warning: Candle at position {i+1} has no candle_number, using sequential")
                        
                        # Calculate text size for background
                        (text_width, text_height), baseline = cv2.getTextSize(
                            number_text, cv2.FONT_HERSHEY_SIMPLEX, NUMBER_FONT_SCALE, NUMBER_FONT_THICKNESS
                        )
                        
                        # Position the number above the wick
                        number_x = int(x_center - text_width / 2)
                        number_y = high_y - NUMBER_OFFSET_ABOVE_WICK
                        
                        # Draw white background for better readability
                        bg_x1 = number_x - NUMBER_BG_PADDING
                        bg_y1 = number_y - text_height - NUMBER_BG_PADDING
                        bg_x2 = number_x + text_width + NUMBER_BG_PADDING
                        bg_y2 = number_y + NUMBER_BG_PADDING
                        
                        # Ensure background stays within image bounds
                        bg_x1 = max(0, bg_x1)
                        bg_y1 = max(0, bg_y1)
                        bg_x2 = min(img_width, bg_x2)
                        bg_y2 = min(BASE_HEIGHT, bg_y2)
                        
                        # Draw white rectangle background
                        cv2.rectangle(chart_img, (bg_x1, bg_y1), (bg_x2, bg_y2), (255, 255, 255), -1)
                        
                        # Draw black border around background for better visibility
                        cv2.rectangle(chart_img, (bg_x1, bg_y1), (bg_x2, bg_y2), (0, 0, 0), 1)
                        
                        # Draw the number in black
                        cv2.putText(chart_img, number_text, (number_x, number_y),
                                cv2.FONT_HERSHEY_SIMPLEX, NUMBER_FONT_SCALE, (0, 0, 0), NUMBER_FONT_THICKNESS)
                    
                    # -----------------------------------------------------------------
                    # RECORD CANDLE COORDINATES IN THE ORIGINAL DATA STRUCTURE
                    # -----------------------------------------------------------------
                    # Only try to record coordinates if we have a valid original_candle that's a dict
                    original_candle = candle.get('original_candle')
                    if original_candle and isinstance(original_candle, dict):
                        # Calculate full candle dimensions (including wick)
                        full_candle_height = abs(low_y - high_y)
                        body_height = abs(body_bottom_y - body_top_y)
                        
                        # Record position data for the FULL candle (including wick)
                        original_candle['candle_x'] = int(x_center)  # Center x-coordinate
                        original_candle['candle_y'] = high_y  # Top of wick (highest point)
                        original_candle['candle_width'] = candle_right_x - candle_left_x  # Body width
                        original_candle['candle_height'] = full_candle_height  # Full height including wick
                        original_candle['candle_left'] = candle_left_x
                        original_candle['candle_right'] = candle_right_x
                        original_candle['candle_top'] = high_y  # Top of wick
                        original_candle['candle_bottom'] = low_y  # Bottom of wick
                        
                        # Record body-specific coordinates
                        original_candle['body_top'] = body_top_y
                        original_candle['body_bottom'] = body_bottom_y
                        original_candle['body_height'] = body_height
                        
                        # Record wick coordinates
                        original_candle['wick_top'] = high_y
                        original_candle['wick_bottom'] = low_y
                        original_candle['wick_x'] = int(x_center)
                        
                        # Also record drawing coordinates (matching the full candle)
                        original_candle['draw_x'] = int(x_center)
                        original_candle['draw_y'] = high_y
                        original_candle['draw_w'] = candle_right_x - candle_left_x
                        original_candle['draw_h'] = full_candle_height
                        original_candle['draw_left'] = candle_left_x
                        original_candle['draw_right'] = candle_right_x
                        original_candle['draw_top'] = high_y
                        original_candle['draw_bottom'] = low_y
                        
                        # Record individual OHLC pixel positions
                        original_candle['open_pixel_y'] = open_y
                        original_candle['high_pixel_y'] = high_y
                        original_candle['low_pixel_y'] = low_y
                        original_candle['close_pixel_y'] = close_y
                        
                        # Add chart metadata
                        original_candle['chart_width'] = img_width
                        original_candle['chart_height'] = BASE_HEIGHT
                        original_candle['chart_timeframe'] = target_tf
                        original_candle['source_timeframe'] = source_tf
                        original_candle['confirmation_key'] = conf_key
                        
                        # Add price range metadata for scaling reference
                        original_candle['chart_min_price'] = min_price
                        original_candle['chart_max_price'] = max_price
                        original_candle['chart_price_range'] = price_range
                
                # Add title with candle count info - CHART NAME FORMAT: {target_tf}_confirmation_from_{source_tf}_poi
                title = f"{sym} {target_tf}_confirmation_from_{source_tf}_poi ({num_candles} candles)"
                
                # Calculate text size to center it
                text_size = cv2.getTextSize(title, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)[0]
                text_x = (img_width - text_size[0]) // 2
                text_y = OUTER_PADDING_TOP // 2
                
                cv2.putText(chart_img, title, (text_x, text_y), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)
                
                # Add detailed info for debugging/verification
                info_text = f"Width:{target_candle_width}px Spacing:{actual_spacing:.1f}px | Inner L:{INNER_PADDING_LEFT} R:{INNER_PADDING_RIGHT} | Img Width:{img_width}px"
                cv2.putText(chart_img, info_text, (OUTER_PADDING_LEFT, BASE_HEIGHT - 10), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (100, 100, 100), 1)
                
                # Save the confirmation chart - FILENAME FORMAT: {target_tf}_confirmation_from_{source_tf}_poi.png
                output_filename = f"{target_tf}_confirmation_from_{source_tf}_poi.png"
                output_path = os.path.join(target_sym_dir, output_filename)
                cv2.imwrite(output_path, chart_img)
                
                log(f"    ✅ Saved chart: {output_filename}")
                chart_count += 1
        
        if chart_count > 0:
            log(f"  📊 Generated {chart_count} confirmation charts for {sym} ")

    def move_confirmation_keys_to_target_timeframes(target_data, dev_base_path, new_folder_name, sym):
        """
        Helper function to reorganize confirmation keys to their target timeframes.
        
        Args:
            target_data: The target_data dictionary containing all timeframe data
            dev_base_path: Base development path
            new_folder_name: New folder name for the entry
            sym: Current symbol being processed
        
        Returns:
            bool: True if any modifications were made, False otherwise
        """
        modified = False
        
        # First, collect all confirmation keys from all timeframes
        confirmation_keys_to_move = []
        for source_tf, tf_data in list(target_data.items()):
            if isinstance(tf_data, dict):
                for key in list(tf_data.keys()):
                    # Check if this is a confirmation key (contains "_confirmation_from_")
                    if "_confirmation_from_" in key:
                        # Parse the key to get the target timeframe
                        # Format: {target_tf}_confirmation_from_{source_tf}_poi_{original_key}
                        parts = key.split('_confirmation_from_')
                        if len(parts) == 2:
                            target_tf = parts[0]  # This is the timeframe where it should belong
                            confirmation_keys_to_move.append({
                                'source_tf': source_tf,
                                'target_tf': target_tf,
                                'key': key,
                                'data': tf_data[key]
                            })
        
        # Now move each confirmation key to its target timeframe
        for item in confirmation_keys_to_move:
            source_tf = item['source_tf']
            target_tf = item['target_tf']
            key = item['key']
            data = item['data']
            
            # Skip if source and target are the same (already in correct place)
            if source_tf == target_tf:
                continue
            
            # Ensure target timeframe exists in target_data
            if target_tf not in target_data:
                target_data[target_tf] = {}
            
            # Check if this key already exists in target timeframe
            if key not in target_data[target_tf]:
                # Move the data to target timeframe
                target_data[target_tf][key] = data
                
                # Remove from source timeframe
                if key in target_data[source_tf]:
                    del target_data[source_tf][key]
                    modified = True
                    
                    # If source timeframe becomes empty after removal, we could optionally remove it
                    # But we'll leave that for cleanup elsewhere
            else:
                # Key already exists in target - we need to merge
                log(f"  ⚠️ Key {key} already exists in {target_tf}, merging data")
                
                # Get existing data
                existing_data = target_data[target_tf][key]
                
                # Create a set of existing timestamps to avoid duplicates
                existing_timestamps = set()
                for candle in existing_data:
                    if 'time' in candle:
                        existing_timestamps.add(candle['time'])
                
                # Add new candles that don't already exist
                new_candles_added = 0
                for candle in data:
                    if 'time' in candle and candle['time'] not in existing_timestamps:
                        existing_data.append(candle)
                        new_candles_added += 1
                
                if new_candles_added > 0:
                    # Sort by time
                    existing_data.sort(key=lambda x: x.get('time', ''))
                    modified = True
                    log(f"    ✅ Added {new_candles_added} new candles to existing data")
                
                # Remove from source timeframe
                if key in target_data[source_tf]:
                    del target_data[source_tf][key]
                    modified = True
        
        return modified
    
    def populate_other_timeframes_with_confirmation_entry(target_data, dev_base_path, new_folder_name, sym):
        """
        Populate original candle lists with confirmation data from their corresponding confirmation keys.
        This overwrites the original candle data with the confirmation data, completely replacing it.
        Creates a backup of the original data under a 'backup' key before overwriting.
        
        Args:
            target_data: The target_data dictionary containing all timeframe data
            dev_base_path: Base development path
            new_folder_name: New folder name for the entry
            sym: Current symbol being processed
        
        Returns:
            bool: True if any modifications were made, False otherwise
        """
        modified = False
        
        # First, collect all confirmation keys and map them to their target candle lists
        # Format: {target_tf}_confirmation_from_{source_tf}_poi_{original_key}
        # We need to map this to: original_key (without the prefix) in the target_tf
        
        for tf, tf_data in target_data.items():
            if not isinstance(tf_data, dict):
                continue
                
            # Find all confirmation keys in this timeframe
            confirmation_keys = []
            for key in list(tf_data.keys()):
                if "_confirmation_from_" in key:
                    # Parse the key to understand what it's confirming
                    # Format: {target_tf}_confirmation_from_{source_tf}_poi_{original_key}
                    parts = key.split('_confirmation_from_')
                    if len(parts) == 2:
                        target_tf = parts[0]  # The timeframe this confirmation belongs to
                        remainder = parts[1]
                        
                        # Further split to get source_tf and original_key
                        # remainder format: {source_tf}_poi_{original_key}
                        source_parts = remainder.split('_poi_')
                        if len(source_parts) == 2:
                            source_tf = source_parts[0]
                            original_key = source_parts[1]
                            
                            confirmation_keys.append({
                                'timeframe': tf,
                                'key': key,
                                'data': tf_data[key],
                                'target_tf': target_tf,
                                'source_tf': source_tf,
                                'original_key': original_key
                            })
            
            # Now process each confirmation key to populate its target candle lists
            for conf_item in confirmation_keys:
                conf_tf = conf_item['timeframe']
                conf_key = conf_item['key']
                conf_data = conf_item['data']
                target_tf = conf_item['target_tf']
                source_tf = conf_item['source_tf']
                original_key = conf_item['original_key']
                
                # We want to populate candle lists in the target_tf (where the confirmation belongs)
                # Look for candle lists in target_tf that match patterns related to the original_key
                
                if target_tf in target_data and isinstance(target_data[target_tf], dict):
                    target_tf_data = target_data[target_tf]
                    
                    # Find all candle lists in this timeframe that should be updated
                    # These would be keys that contain the original_key or are the original_key itself
                    candle_lists_to_update = []
                    
                    for candle_key in list(target_tf_data.keys()):
                        # Skip if this is a patterns key or a confirmation key
                        if candle_key.endswith('_patterns') or '_confirmation_from_' in candle_key:
                            continue
                        
                        # Check if this candle list should be updated with confirmation data
                        # It should be updated if it's related to the original_key
                        # This includes:
                        # 1. Exact match with original_key
                        # 2. Keys that contain original_key as a suffix (like "PREFIX_original_key")
                        # 3. Keys that are the base name without the new_folder_name prefix
                        
                        candle_key_lower = candle_key.lower()
                        original_key_lower = original_key.lower()
                        
                        # Check for various matching patterns
                        should_update = (
                            candle_key == original_key or  # Exact match
                            candle_key.endswith(f"_{original_key}") or  # Suffix match
                            candle_key_lower.endswith(f"_{original_key_lower}") or  # Case insensitive suffix
                            original_key_lower in candle_key_lower or  # Contains the original key
                            candle_key.replace(f"{new_folder_name}_", "") == original_key  # Without prefix
                        )
                        
                        if should_update:
                            candle_lists_to_update.append(candle_key)
                    
                    # Also check for keys that might be the base pattern name
                    # For example, if original_key is "swing_points", also look for 
                    # "STRUCTURAL-LIQUIDITY_swing_points" and similar
                    for candle_key in list(target_tf_data.keys()):
                        if candle_key.endswith('_patterns') or '_confirmation_from_' in candle_key:
                            continue
                        
                        # If the candle_key contains the original_key as a suffix after an underscore
                        parts = candle_key.split('_')
                        if len(parts) > 1 and parts[-1] == original_key:
                            if candle_key not in candle_lists_to_update:
                                candle_lists_to_update.append(candle_key)
                    
                    # Remove duplicates
                    candle_lists_to_update = list(set(candle_lists_to_update))
                    
                    # Now update each identified candle list with the confirmation data
                    if candle_lists_to_update:
                        
                        # Create backup of original data before overwriting
                        # We only need one backup since all candle lists being updated have the same data
                        # (they all correspond to the same original pattern)
                        
                        # Get the first candle list to backup (they all have the same data)
                        first_candle_key = candle_lists_to_update[0]
                        original_data = target_tf_data.get(first_candle_key, [])
                        
                        # Create backup key name based on the original_key
                        # Format: backup_original_key
                        backup_key = f"backup"
                        
                        # Only create backup if it doesn't already exist
                        if backup_key not in target_tf_data:
                            target_tf_data[backup_key] = original_data.copy()
                            modified = True
                        
                        # Now update all candle lists with confirmation data
                        for candle_key in candle_lists_to_update:
                            # COMPLETELY REPLACE the original data with confirmation data
                            # This is what the user requested: overwrite/remove original
                            target_tf_data[candle_key] = conf_data.copy()
                            modified = True
        
        return modified
    
    def filter_empty_symbol_folders(dev_base_path, folder_name):
        """
        Remove symbol folders that contain no files (empty directories).
        
        Args:
            dev_base_path: Base development path
            folder_name: Name of the folder containing symbol subfolders
            
        Returns:
            int: Number of empty folders deleted
        """
        folder_path = os.path.join(dev_base_path, folder_name)
        if not os.path.exists(folder_path):
            log(f"Folder {folder_path} does not exist, skipping empty folder filter")
            return 0
        
        deleted_count = 0
        
        # Iterate through all items in the folder
        for item_name in os.listdir(folder_path):
            item_path = os.path.join(folder_path, item_name)
            
            # Only process directories (symbol folders)
            if os.path.isdir(item_path):
                # Check if directory is empty (no files/subdirectories)
                if not os.listdir(item_path):
                    try:
                        shutil.rmtree(item_path)
                        deleted_count += 1
                    except Exception as e:
                        log(f"   Error deleting empty folder {item_name}: {e}")
        
        
        return deleted_count

    def swap_from_key_swing_type_values_to_target(target_data, dev_base_path, new_folder_name, sym, data_swapping_config):
        """
        Swaps swing_type values from a source key to a target key across all timeframes and confirmation data.
        
        Args:
            target_data: The target_data dictionary containing all timeframe data
            dev_base_path: Base development path
            new_folder_name: New folder name for the entry
            sym: Current symbol being processed
            data_swapping_config: Dictionary with 'from' and 'to' keys (e.g., {"from": "swing_points2", "to": "swing_points"})
        
        Returns:
            bool: True if any modifications were made, False otherwise
        """
        # Validate input
        if not data_swapping_config:
            log(f"  ⏭️ No data_swapping configuration for {sym}")
            return False
        
        from_key = data_swapping_config.get("from")
        to_key = data_swapping_config.get("to")
        
        if not from_key or not to_key:
            log(f"  ⏭️ Missing 'from' or 'to' key in data_swapping config for {sym}")
            return False
        
        log(f"\n  🔄 SWING TYPE SWAPPING for {sym}")
        log(f"     From: '{from_key}' → To: '{to_key}'")
        
        # Track modifications
        modified = False
        total_candles_updated = 0
        
        # First, identify all timeframes in target_data
        for tf, tf_data in list(target_data.items()):
            if not isinstance(tf_data, dict):
                continue
            
            # Look for all keys that contain the target 'to_key' (including confirmation keys)
            keys_to_update = []
            
            # Check each key in this timeframe
            for key in tf_data.keys():
                # Check if this key matches the exact 'to_key' or is a pattern key that contains it
                if key == to_key or key.endswith(f"_{to_key}") or key == f"{new_folder_name}_{to_key}":
                    keys_to_update.append(key)
                # Also check for confirmation keys that might contain the target pattern
                elif "_confirmation_from_" in key and to_key in key:
                    keys_to_update.append(key)
            
            if not keys_to_update:
                continue
            
            log(f"\n  📁 Timeframe: {tf}")
            
            # For each key to update, process its candles
            for target_key in keys_to_update:
                target_candles = tf_data.get(target_key, [])
                
                if not target_candles:
                    log(f"     ⏭️ Key '{target_key}' has no candle data")
                    continue
                
                # Debug: Show first candle's current swing_type
                if target_candles and len(target_candles) > 0:
                    first_candle = target_candles[0]
                    first_candle_time = first_candle.get('time', 'N/A')
                    first_candle_number = first_candle.get('candle_number', 'N/A')
                    first_swing_type = first_candle.get('swing_type', 'N/A')
                    log(f"\n     📍 Processing key: '{target_key}'")
                    log(f"        Example candle #{first_candle_number} (time: {first_candle_time[:50] if first_candle_time != 'N/A' else 'N/A'}...)")
                    log(f"        Current swing_type: {first_swing_type}")
                
                # Now we need to access the source data (from_key) for this timeframe
                # Source data path: dev_base_path/{sym}/{tf}/config.json
                source_config_path = os.path.join(dev_base_path, sym, tf, "config.json")
                
                if not os.path.exists(source_config_path):
                    log(f"        ⚠️ Source config not found: {source_config_path}")
                    continue
                
                try:
                    with open(source_config_path, 'r', encoding='utf-8') as f:
                        source_data = json.load(f)
                    
                    # Get the source candles from the from_key
                    source_candles = source_data.get(from_key, [])
                    
                    if not source_candles:
                        log(f"        ⚠️ Source key '{from_key}' not found or empty in {source_config_path}")
                        continue
                    
                    # Build lookup dictionaries for quick access by candle_number and time
                    source_by_candle_number = {}
                    source_by_timestamp = {}
                    
                    for candle in source_candles:
                        candle_number = candle.get('candle_number')
                        timestamp = candle.get('time')
                        
                        if candle_number is not None:
                            source_by_candle_number[candle_number] = candle
                        if timestamp:
                            source_by_timestamp[timestamp] = candle
                    
                    log(f"        ✅ Loaded {len(source_candles)} candles from source key '{from_key}'")
                    
                    # Update each target candle if matching source found
                    candles_updated_in_key = 0
                    
                    for i, target_candle in enumerate(target_candles):
                        target_candle_number = target_candle.get('candle_number')
                        target_timestamp = target_candle.get('time')
                        
                        # Try to find source candle by candle_number first, then by timestamp
                        source_candle = None
                        match_method = None
                        
                        if target_candle_number is not None and target_candle_number in source_by_candle_number:
                            source_candle = source_by_candle_number[target_candle_number]
                            match_method = f"candle_number {target_candle_number}"
                        elif target_timestamp and target_timestamp in source_by_timestamp:
                            source_candle = source_by_timestamp[target_timestamp]
                            match_method = "timestamp"
                        
                        if source_candle:
                            source_swing_type = source_candle.get('swing_type')
                            
                            if source_swing_type is not None:
                                # Get current swing_type for comparison
                                current_swing_type = target_candle.get('swing_type')
                                
                                # Only update if different
                                if current_swing_type != source_swing_type:
                                    # Update the swing_type
                                    target_candle['swing_type'] = source_swing_type
                                    target_candles[i] = target_candle  # Update in place
                                    candles_updated_in_key += 1
                                    total_candles_updated += 1
                                    
                                    # Debug output for first few updates
                                    if candles_updated_in_key <= 3:
                                        log(f"           🔄 Updated candle #{target_candle_number} (time: {target_timestamp[:50] if target_timestamp else 'N/A'}...)")
                                        log(f"              Swing_type: {current_swing_type} → {source_swing_type} (matched by {match_method})")
                    
                    if candles_updated_in_key > 0:
                        # Update the key in tf_data
                        tf_data[target_key] = target_candles
                        modified = True
                        log(f"        ✅ Updated {candles_updated_in_key} candles in '{target_key}'")
                        
                        # Show updated first candle as confirmation
                        if target_candles and len(target_candles) > 0:
                            updated_first = target_candles[0]
                            updated_swing_type = updated_first.get('swing_type', 'N/A')
                            log(f"        📊 After update: First candle swing_type = {updated_swing_type}")
                    else:
                        log(f"        ⏭️ No matching source candles found for '{target_key}'")
                        
                except Exception as e:
                    log(f"         Error processing {source_config_path}: {e}")
        
        # Also check confirmation data that might have been moved to target timeframes
        # The populate_other_timeframes_with_confirmation_entry might have created backup keys
        # We need to ensure any confirmation data also gets updated
        
        # Re-scan all timeframes again to catch any newly created/updated keys
        for tf, tf_data in list(target_data.items()):
            if not isinstance(tf_data, dict):
                continue
                
            # Look for backup keys that might contain the target pattern
            for key in list(tf_data.keys()):
                if key.startswith("backup") and to_key in key:
                    backup_candles = tf_data.get(key, [])
                    if backup_candles:
                        log(f"\n  📁 Checking backup key: '{key}' in {tf}")
                        
                        # Process backup data similarly
                        source_config_path = os.path.join(dev_base_path, sym, tf, "config.json")
                        if os.path.exists(source_config_path):
                            try:
                                with open(source_config_path, 'r', encoding='utf-8') as f:
                                    source_data = json.load(f)
                                
                                source_candles = source_data.get(from_key, [])
                                if source_candles:
                                    # Build lookup
                                    source_by_candle_number = {}
                                    source_by_timestamp = {}
                                    for candle in source_candles:
                                        candle_number = candle.get('candle_number')
                                        timestamp = candle.get('time')
                                        if candle_number is not None:
                                            source_by_candle_number[candle_number] = candle
                                        if timestamp:
                                            source_by_timestamp[timestamp] = candle
                                    
                                    # Update backup candles
                                    backup_updated = 0
                                    for i, backup_candle in enumerate(backup_candles):
                                        target_candle_number = backup_candle.get('candle_number')
                                        target_timestamp = backup_candle.get('time')
                                        
                                        source_candle = None
                                        if target_candle_number is not None and target_candle_number in source_by_candle_number:
                                            source_candle = source_by_candle_number[target_candle_number]
                                        elif target_timestamp and target_timestamp in source_by_timestamp:
                                            source_candle = source_by_timestamp[target_timestamp]
                                        
                                        if source_candle:
                                            source_swing_type = source_candle.get('swing_type')
                                            if source_swing_type is not None and backup_candle.get('swing_type') != source_swing_type:
                                                backup_candle['swing_type'] = source_swing_type
                                                backup_candles[i] = backup_candle
                                                backup_updated += 1
                                                total_candles_updated += 1
                                    
                                    if backup_updated > 0:
                                        tf_data[key] = backup_candles
                                        modified = True
                                        log(f"        ✅ Updated {backup_updated} candles in backup key '{key}'")
                            except Exception as e:
                                log(f"         Error processing backup {key}: {e}")
        
        if total_candles_updated > 0:
            log(f"\n  ✅ SWING TYPE SWAPPING COMPLETE: Updated {total_candles_updated} candles across all timeframes for {sym}")
        else:
            log(f"\n  ⏭️ No swing type updates performed for {sym}")
        
        return modified

    def process_entry_confirmation_newfilename(entry_settings, source_def_name, raw_filename_base, base_folder, dev_base_path, symbols_dictionary=None):
        new_folder_name = entry_settings.get("new_filename")
        if not new_folder_name:
            return 0
        
        # --- CHECK IF ENTRY CONFIRMATION IS ENABLED AT THE START ---
        entry_confirmation_enabled = entry_settings.get("enable_entry_poi_confirmation", False)
        if entry_confirmation_enabled:
            log(f"  ✅ Entry POI Confirmation is ENABLED for {new_folder_name}")
        else:
            log(f"  ⏭️ Entry POI Confirmation is DISABLED for {new_folder_name} - skipping confirmation processing")
            # If confirmation is disabled, we can return early as this function only handles confirmation
            return 0
        
        # Add timeframe hierarchy for ordering (from highest to lowest)
        tf_hierarchy = ['1M', '1W', '3D', '1D', '12h', '8h', '6h', '4h', '3h', '2h', '1h', '45m', '30m', '15m', '5m', '3m', '1m']
        
        # --- Symbol Filtering Logic (CASE INSENSITIVE) ---
        if symbols_dictionary is None:
            symbols_dictionary = entry_settings.get("symbols_dictionary", {})
        
        target_symbols = None
        new_folder_name_lower = new_folder_name.lower()
        
        matching_key = None
        for key in symbols_dictionary.keys():
            if key.lower() == new_folder_name_lower:
                matching_key = key
                break
        
        if matching_key:
            symbol_groups = symbols_dictionary[matching_key]
            log(f"{new_folder_name} targets specific symbols")
            
            all_symbols = []
            if isinstance(symbol_groups, dict):
                for group_name, symbol_list in symbol_groups.items():
                    if isinstance(symbol_list, list):
                        all_symbols.extend(symbol_list)
            elif isinstance(symbol_groups, list):
                all_symbols = symbol_groups
                log(f"  Direct symbol list: {symbol_groups}")
            
            if all_symbols:
                target_symbols = set(all_symbols)
            else:
                log(f"{matching_key} activates processing all symbols")
        else:
            log(f"{new_folder_name} accepts all symbols")
        
        mark_paused_symbols_in_full_candles(dev_base_path, new_folder_name)
        identify_paused_symbols_poi(dev_base_path, new_folder_name)
        limit_orders_old_record_cleanup(dev_base_path, new_folder_name)

        # Load paused symbols
        paused_symbols_file = os.path.join(dev_base_path, new_folder_name, "paused_symbols_folder", "paused_symbols.json")
        paused_names = set()
        
        if os.path.exists(paused_symbols_file):
            try:
                with open(paused_symbols_file, 'r', encoding='utf-8') as f:
                    paused_list = json.load(f)
                    paused_names = {item.get("symbol") for item in paused_list if "symbol" in item}
            except Exception as e:
                log(f"Error loading paused symbols: {e}")

        process_receiver = str(entry_settings.get("process_receiver_files", "no")).lower()
        identify_config = entry_settings.get("identify_definitions", {})
        sync_count = 0

        if target_symbols:
            log(f"🚀 PROCESSING ONLY these symbols for {new_folder_name}: {sorted(target_symbols)}")
        else:
            log(f"📁 Processing ALL symbols for {new_folder_name} (no filtering)")

        for sym in sorted(os.listdir(base_folder)):
            sym_p = os.path.join(base_folder, sym)
            
            if not os.path.isdir(sym_p):
                continue
                
            if target_symbols is not None and sym not in target_symbols:
                continue
                
            if sym in paused_names:
                log(f"  ⏸️ Skipping {sym} - paused")
                continue

            target_sym_dir = os.path.join(dev_base_path, new_folder_name, sym)
            os.makedirs(target_sym_dir, exist_ok=True)
            
            target_config_path = os.path.join(target_sym_dir, "config.json")
            
            # Skip if target config doesn't exist (nothing to enrich)
            if not os.path.exists(target_config_path):
                continue
                
            # Load target data
            try:
                with open(target_config_path, 'r', encoding='utf-8') as f:
                    target_data = json.load(f)
            except Exception as e:
                log(f"Error loading target config for {sym}: {e}")
                continue

            modified = False
            pending_images = {}
            pending_full_candle_data = {}

            # Get all timeframes from target_data (not from source folders)
            timeframes = sorted([tf for tf in target_data.keys() if tf in tf_hierarchy], 
                            key=lambda x: tf_hierarchy.index(x) if x in tf_hierarchy else len(tf_hierarchy))
            
            for tf in timeframes:
                if tf not in target_data:
                    continue
                    
                # Get all higher timeframes (for confirmation sources)
                higher_tfs = []
                if tf in tf_hierarchy:
                    tf_index = tf_hierarchy.index(tf)
                    higher_tfs = tf_hierarchy[:tf_index]  # All timeframes higher than current
                
                # Process each file_key in this timeframe
                for file_key in list(target_data[tf].keys()):
                    # Skip pattern keys and metadata
                    if file_key.endswith("_patterns") or file_key == "_metadata":
                        continue
                        
                    clean_key = file_key.lower()
                    
                    # Check if this is a primary or receiver file based on naming
                    is_primary = (clean_key == source_def_name.lower() or clean_key == raw_filename_base)
                    is_receiver = (not is_primary and raw_filename_base in clean_key)
                    
                    # Skip if it's a receiver file but we're not processing receivers
                    if (is_receiver and process_receiver != "yes") or (not is_primary and not is_receiver):
                        continue
                    
                    # Get the candle data from target
                    candles = target_data[tf].get(file_key, [])
                    if not candles:
                        continue
                    
                    # Find existing confirmation keys for this timeframe and file_key
                    # Pattern: {current_tf}_confirmation_from_{higher_tf}_poi_{file_key}
                    matching_keys = []
                    
                    # Look for keys that match the pattern
                    for existing_key in target_data[tf].keys():
                        if existing_key.startswith(f"{tf}_confirmation_from_") and existing_key.endswith(f"_poi_{file_key}"):
                            # Extract the source timeframe
                            source_tf_part = existing_key.replace(f"{tf}_confirmation_from_", "").split("_poi_")[0]
                            if source_tf_part in higher_tfs:
                                matching_keys.append(existing_key)
                    
                    # Process each matching key
                    for new_key in matching_keys:
                        # IMPORTANT CHANGE: Check if this key already has patterns (indicates it's already enriched)
                        if f"{new_key}_patterns" in target_data[tf]:
                            log(f"  ⏭️ [{sym}] {new_key} already enriched with patterns, skipping")
                            continue
                        
                        # Extract source timeframe from the key for chart naming
                        source_tf = new_key.replace(f"{tf}_confirmation_from_", "").split("_poi_")[0]
                        chart_base_name = f"{tf}_confirmation_from_{source_tf}_poi"
                        
                        if identify_config:
                            # Apply swing points liquidity first
                            swing_points_liquidity(target_data[tf], new_key, candles, identify_config)
                            
                            # Process using the candle data from target
                            processed_candles = identify_definitions({file_key: candles}, identify_config, source_def_name, raw_filename_base)
                            
                            if file_key in processed_candles:
                                updated_candles, extracted_patterns = apply_definitions_condition(
                                    processed_candles[file_key], identify_config, new_folder_name, file_key
                                )
                                
                                # Update existing key with new data
                                target_data[tf][new_key] = updated_candles
                                
                                if extracted_patterns:
                                    target_data[tf][f"{new_key}_patterns"] = extracted_patterns
                                    
                                    # --- ADDED: Call add_liquidity_sweepers_to_patterns immediately after patterns are created ---
                                    # Get original candles for liquidity sweepers
                                    if "_confirmation_from_" in new_key:
                                        parts = new_key.split("_poi_")
                                        if len(parts) > 1:
                                            original_candles_key = parts[1]
                                        else:
                                            original_candles_key = new_key.split("_poi_")[0].split("_confirmation_from_")[1]
                                    else:
                                        original_candles_key = new_key.replace(f"{new_folder_name}_", "")
                                    
                                    original_candles = target_data[tf].get(original_candles_key, [])
                                    
                                    if original_candles:
                                        add_liquidity_sweepers_to_patterns(target_data[tf], new_key, original_candles)
                                        
                                        # --- MOVED: Call liquidity_flags_to_sweepers immediately after adding sweepers ---
                                        patterns_key = f"{new_key}_patterns"
                                        if patterns_key in target_data[tf]:
                                            liquidity_flags_to_sweepers(target_data[tf], patterns_key, identify_config)
                                
                                modified = True
                                
                                processed_candles = intruder_and_outlaw_check(processed_candles)
                                
                                poi_config = entry_settings.get("point_of_interest")
                                if poi_config:
                                    identify_poi(target_data[tf], new_key, updated_candles, poi_config)
                                    identify_poi_mitigation(target_data[tf], new_key, poi_config)
                                    identify_swing_mitigation_between_definitions(target_data[tf], new_key, updated_candles, poi_config)
                                    identify_selected(target_data[tf], new_key, poi_config)
                                    # --- NEW: Remove outlawed swings between definitions ---
                                    # This must be called AFTER identify_selected and BEFORE POI drawing
                                    # It checks the FULL candle data for any swing between definitions
                                    remove_outlawed_swings_in_between_definitions(
                                        target_data[tf], 
                                        new_key, 
                                        candles,  # Pass the FULL original candles
                                        poi_config
                                    )

                    # Process full_candles_data.json from target symbol directory
                    target_full_candle_path = os.path.join(target_sym_dir, f"{tf}_full_candles_data.json")
                    if os.path.exists(target_full_candle_path):
                        try:
                            with open(target_full_candle_path, 'r', encoding='utf-8') as f:
                                full_data_content = json.load(f)
                                # Create a reference in the same format as pending_full_candle_data in process_entry
                                full_candles_ref_key = f"{tf}_full_candles_ref_{file_key}"
                                pending_full_candle_data[full_candles_ref_key] = {
                                    "tf": tf,
                                    "config_key": file_key,
                                    "target_data_ref": target_data[tf],
                                    "target_key": file_key
                                }
                        except Exception as e:
                            log(f"Error reading full_candles_data for {sym} {tf}: {e}")
            
            # Process Ticks JSON (still from source since ticks are separate)
            source_ticks_path = os.path.join(dev_base_path, sym, f"{sym}_ticks.json")
            if os.path.exists(source_ticks_path):
                target_ticks_path = os.path.join(target_sym_dir, f"{sym}_ticks.json")
                try:
                    with open(source_ticks_path, 'r', encoding='utf-8') as f:
                        ticks_data = json.load(f)
                    with open(target_ticks_path, 'w', encoding='utf-8') as f:
                        json.dump(ticks_data, f, indent=4)
                except Exception as e:
                    log(f"Error processing ticks for {sym}: {e}")
            
            # =================================================================
            # INTEGRATED SANITIZE LOGIC (replaces sanitize_symbols_or_files call)
            # =================================================================
            # Determine which timeframes have patterns
            tfs_to_keep = []
            tfs_to_remove = []

            for tf, tf_content in list(target_data.items()):
                has_patterns = any(key.endswith("_patterns") and value for key, value in tf_content.items())
                
                if has_patterns:
                    tfs_to_keep.append(tf)
                else:
                    tfs_to_remove.append(tf)

            # If no timeframes have patterns, the whole symbol is invalid - delete the folder
            if not tfs_to_keep:
                if os.path.exists(target_sym_dir):
                    shutil.rmtree(target_sym_dir)
                continue  # Skip to next symbol

            # =================================================================
            # END INTEGRATED SANITIZE LOGIC
            # =================================================================

            identify_paused_symbols(target_data, dev_base_path, new_folder_name)
            populate_limit_orders_with_paused_orders(dev_base_path, new_folder_name)

            # -----------------------------------------------------------------
            # NEW: Add POI Confirmation Extraction (like process_entry)
            # -----------------------------------------------------------------
            # Get the POI confirmation timeframes from entry settings
            poi_confirmation_timeframes = entry_settings.get("poi_confirmation_timeframes", {})
            
            for tf in tfs_to_keep:
                if tf in target_data:
                    for file_key in list(target_data[tf].keys()):
                        if file_key.endswith("_patterns"):
                            # Extract base key (remove '_patterns' suffix)
                            base_key = file_key.replace("_patterns", "")
                            
                            # Call the POI extraction function for this pattern, passing pending_full_candle_data
                            original_target_data = target_data[tf].copy()  # Keep a copy for reference
                            result = extract_poi_to_confirmation(
                                target_data[tf], 
                                base_key, 
                                dev_base_path, 
                                new_folder_name, 
                                sym,
                                pending_full_candle_data,  # Pass the queued full candle references
                                poi_confirmation_timeframes  # Pass the configuration
                            )
                            
                            # Check if anything was added/modified
                            if result != original_target_data:
                                target_data[tf] = result
                                modified = True
                                log(f"  📊 Added POI confirmation candles for {sym} {tf}")

            # -----------------------------------------------------------------
            # GENERATE CONFIRMATION CHARTS (like process_entry)
            # -----------------------------------------------------------------
            generate_confirmation_charts(
                dev_base_path,
                new_folder_name,
                sym,
                target_sym_dir,
                target_data,
                pending_full_candle_data,
                tfs_to_keep,  # Pass the list of timeframes to keep
                poi_confirmation_timeframes  # Pass the configuration for filtering
            )

            # -----------------------------------------------------------------
            # MOVE CONFIRMATION KEYS TO TARGET TIMEFRAMES (like process_entry)
            # -----------------------------------------------------------------
            if move_confirmation_keys_to_target_timeframes(target_data, dev_base_path, new_folder_name, sym):
                modified = True

            # -----------------------------------------------------------------
            # POPULATE OTHER TIMEFRAMES WITH CONFIRMATION ENTRY DATA (like process_entry)
            # -----------------------------------------------------------------
            if populate_other_timeframes_with_confirmation_entry(target_data, dev_base_path, new_folder_name, sym):
                modified = True

            data_swapping_config = entry_settings.get("data_swapping")
            if data_swapping_config:
                log(f"  🔄 Processing data_swapping for {sym}")
                if swap_from_key_swing_type_values_to_target(target_data, dev_base_path, new_folder_name, sym, data_swapping_config):
                    modified = True
            else:
                log(f"  ⏭️ No data_swapping configuration for {sym}")

            # STEP 4 ADD DEFINITIONS LIQUIDITY TO PATTERNS - Now redundant as we already did it above
            # But keeping for backward compatibility with any patterns that might have been created elsewhere
            for tf in tfs_to_keep:
                if tf in target_data:
                    for file_key in list(target_data[tf].keys()):
                        if file_key.endswith("_patterns"):
                            base_key = file_key.replace("_patterns", "")
                            
                            # Extract original candles key from pattern key
                            if "_confirmation_from_" in base_key:
                                parts = base_key.split("_poi_")
                                if len(parts) > 1:
                                    original_candles_key = parts[1]
                                else:
                                    original_candles_key = base_key.split("_poi_")[0].split("_confirmation_from_")[1]
                            else:
                                original_candles_key = base_key.replace(f"{new_folder_name}_", "")
                            
                            original_candles = target_data[tf].get(original_candles_key, [])
                            
                            if original_candles:
                                add_liquidity_sweepers_to_patterns(target_data[tf], base_key, original_candles)
                                
                                # Also add liquidity flags to sweepers for any patterns created here
                                liquidity_flags_to_sweepers(target_data[tf], file_key, identify_config)

            # =================================================================
            # NOW DRAW ALL IMAGES WITH SWEEPERS INCLUDED
            # =================================================================
            
            # Re-iterate through timeframes to draw images now that sweepers are added
            for tf in timeframes:
                if tf not in target_data or tf not in tfs_to_keep:
                    continue
                    
                # Get all higher timeframes (for confirmation sources)
                higher_tfs = []
                if tf in tf_hierarchy:
                    tf_index = tf_hierarchy.index(tf)
                    higher_tfs = tf_hierarchy[:tf_index]
                
                # Process each file_key in this timeframe
                for file_key in list(target_data[tf].keys()):
                    # Skip pattern keys and metadata
                    if file_key.endswith("_patterns") or file_key == "_metadata":
                        continue
                        
                    clean_key = file_key.lower()
                    
                    # Check if this is a primary or receiver file based on naming
                    is_primary = (clean_key == source_def_name.lower() or clean_key == raw_filename_base)
                    is_receiver = (not is_primary and raw_filename_base in clean_key)
                    
                    # Skip if it's a receiver file but we're not processing receivers
                    if (is_receiver and process_receiver != "yes") or (not is_primary and not is_receiver):
                        continue
                    
                    # Find existing confirmation keys for this timeframe and file_key
                    matching_keys = []
                    for existing_key in target_data[tf].keys():
                        if existing_key.startswith(f"{tf}_confirmation_from_") and existing_key.endswith(f"_poi_{file_key}"):
                            source_tf_part = existing_key.replace(f"{tf}_confirmation_from_", "").split("_poi_")[0]
                            if source_tf_part in higher_tfs:
                                matching_keys.append(existing_key)
                    
                    # Process each matching key for drawing
                    for new_key in matching_keys:
                        source_tf = new_key.replace(f"{tf}_confirmation_from_", "").split("_poi_")[0]
                        chart_base_name = f"{tf}_confirmation_from_{source_tf}_poi"
                        
                        # Handle chart images
                        existing_img_path = os.path.join(target_sym_dir, f"{chart_base_name}.png")
                        
                        if os.path.exists(existing_img_path):
                            img = cv2.imread(existing_img_path)
                            if img is not None:
                                
                                poi_config = entry_settings.get("point_of_interest")
                                if poi_config:
                                    identify_candle_after_poi_and_apply_condition(target_data[tf], new_key, candles, poi_config, identify_config)
                                    img = draw_poi_tools(img, target_data[tf], new_key, poi_config)
                                    record_config = entry_settings.get("record_prices")
                                    if record_config:
                                        identify_pending_prices(target_data[tf], new_key, record_config, dev_base_path, new_folder_name)

                                        # --- ADDED: Call identify_hitler_prices immediately after identify_prices ---
                                        patterns_key = f"{new_key}_patterns"
                                        if patterns_key in target_data[tf]:
                                            identify_hitler_prices(
                                                target_data[tf], 
                                                new_key, 
                                                record_config,
                                                dev_base_path, 
                                                new_folder_name,
                                                target_data  # Pass the full target_data for cross-timeframe checking
                                            )
                                            poi_order_direction_validation(target_data[tf], patterns_key)
                                        
                                
                                # Draw definition tools NOW that sweepers and flags are in the patterns
                                if identify_config:
                                    patterns_key = f"{new_key}_patterns"
                                    if patterns_key in target_data[tf]:
                                        # No need to call liquidity_flags_to_sweepers here as it's already done
                                        img = draw_definition_tools(img, target_data[tf], patterns_key, identify_config)
                                
                                # Queue the image to be saved
                                pending_images[f"{chart_base_name}.png"] = (tf, img, new_key)

            # --- Final Write (Images) ---
            # Save all pending images
            for img_name, (tf, img_data, new_key) in pending_images.items():
                img_path = os.path.join(target_sym_dir, img_name)
                cv2.imwrite(img_path, img_data)
                log(f"  💾 [{sym}] {img_name} confirmation completed")

            if modified:
                with open(target_config_path, 'w', encoding='utf-8') as f:
                    json.dump(target_data, f, indent=4)
                sync_count += 1

        if target_symbols:
            log(f"✅ PROCESSED {new_folder_name} {sync_count} SYMBOLS POI CONFIRMATION")
        filter_empty_symbol_folders(dev_base_path, new_folder_name)
            
        return sync_count

    def main_logic():
        """Main logic for processing entry points of interest."""
        log(f"Starting: {user_id}")

        # 1. Load developers dictionary
        dev_dict = load_developers_dictionary() 
        cfg = dev_dict.get(str(user_id))
        if not cfg:
            log(f"User {user_id} not found")
            return f"Error: User {user_id} not in dictionary."
        
        # 2. Set up paths
        dev_base_path = os.path.join(DEV_PATH, str(user_id))
        base_folder = os.path.join(dev_base_path, "ohlc")
        
        # 3. Get accountmanagement from developers.json (NOT from file system)
        am_data = get_account_management(str(user_id))
        if not am_data:
            log("accountmanagement configuration missing in developers.json")
            return "Error: accountmanagement configuration missing in developers.json."

        # 4. Extract configuration from accountmanagement
        symbols_dictionary = am_data.get("symbols_dictionary", {})
        define_candles = am_data.get("chart", {}).get("define_candles", {})
        
        # 5. Get the confirmation entries (note: different key from POI condition)
        entries_root = define_candles.get("entries_poi_confirmation_condition", {})
        
        total_syncs = 0
        entry_count = 0

        # 6. Process each entry
        for apprehend_key, source_configs in entries_root.items():
            if not apprehend_key.startswith("apprehend_"):
                continue
                
            source_def_name = apprehend_key.replace("apprehend_", "")
            source_def = define_candles.get(source_def_name, {})
            if not source_def:
                continue

            raw_filename_base = source_def.get("filename", "").replace(".json", "").lower()

            for entry_key, entry_settings in source_configs.items():
                if not entry_key.startswith("entry_"):
                    continue

                new_folder_name = entry_settings.get('new_filename')
                if new_folder_name:
                    print()
                    log(f"\n📊 PROCESSING {new_folder_name} POI CONFIRMATION")
                    
                    identify_config = entry_settings.get("identify_definitions")
                    if identify_config:
                        log(f"  With identify_definitions: {list(identify_config.keys())}")
                    
                    entry_count += 1
                    
                    syncs = process_entry_confirmation_newfilename(
                        entry_settings, 
                        source_def_name, 
                        raw_filename_base, 
                        base_folder,
                        dev_base_path,
                        symbols_dictionary
                    )
                    
                    total_syncs += syncs
        
        # 7. Return summary
        if entry_count > 0:
            return f"COMPLETED: {entry_count} ENTRIES CONFIRMATION PROCESSED"
        else:
            return f"No entry points found for processing."
    
    return main_logic()

def clear_unathorized_entries_folders(dev_user_id):
    """
    Cleans up unauthorized folders in a developer's directory.
    
    1. Identifies valid strategy folders from the developer's directory
       (folders that contain a 'pending_orders' subfolder).
    2. Always spares the 'ohlc' folder.
    3. Deletes any OTHER folder at the ROOT level of the developer directory 
       that is NOT a strategy folder and NOT 'ohlc'.
    
    IMPORTANT: Only deletes folders at the root level. Does NOT go into 
    subfolders or delete anything inside ohlc or strategy folders.
    
    Parameters:
    - dev_user_id: The developer's user ID (folder name in DEV_PATH)
    
    Returns:
    - True if successful, False if error
    """
    try:
        # Path for Developer Output
        dev_output_base = os.path.join(DEV_PATH, str(dev_user_id))
        
        # Check if developer folder exists
        if not os.path.exists(dev_output_base):
            print(f"[{dev_user_id}] ⚠️ Developer folder not found: {dev_output_base}")
            return True  # Nothing to clean up

        print(f"\n{'='*60}")
        print(f"🧹 CLEANING UP UNAUTHORIZED FOLDERS FOR USER ID: {dev_user_id}")
        print(f"📂 Path: {dev_output_base}")
        print(f"{'='*60}")

        # --- PART 1: Identify Protected Folders ---
        protected_folders = set()
        
        # 1. Always protect the 'ohlc' folder
        protected_folders.add("ohlc")
        print(f"  🔒 Protected: ohlc (always spared)")
        
        # 2. Find all strategy folders (contain 'pending_orders' subfolder)
        strategy_folders = []
        if os.path.exists(dev_output_base):
            for item in os.listdir(dev_output_base):
                item_path = os.path.join(dev_output_base, item)
                
                # Check if it's a directory and contains a pending_orders folder
                if os.path.isdir(item_path):
                    pending_orders_path = os.path.join(item_path, "pending_orders")
                    if os.path.exists(pending_orders_path) and os.path.isdir(pending_orders_path):
                        strategy_folders.append(item)
                        protected_folders.add(item)
                        print(f"  📁 Protected: {item} (strategy folder with pending_orders)")
        
        if not strategy_folders:
            print(f"  ⚠️ No strategy folders found in developer's directory")
            print(f"  💡 Strategy folders should contain a 'pending_orders' subfolder")
        
        print(f"\n  📋 Total protected folders: {len(protected_folders)}")
        for folder in sorted(protected_folders):
            print(f"    • {folder}")

        # --- PART 2: Cleanup Unauthorized Folders (ROOT LEVEL ONLY) ---
        deleted_count = 0
        unauthorized_folders = []
        
        try:
            # Only iterate through items at the ROOT level of dev_output_base
            for item in os.listdir(dev_output_base):
                item_path = os.path.join(dev_output_base, item)
                
                # Target ONLY directories at the ROOT level
                if os.path.isdir(item_path):
                    # Check if this folder is protected
                    if item not in protected_folders:
                        unauthorized_folders.append(item)
                        shutil.rmtree(item_path)  # This deletes the folder and ALL its contents
                        deleted_count += 1
            
        except Exception as e:
            print(f"[{dev_user_id}]  Cleanup Error: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        # --- Summary ---
        print(f"\n{'='*60}")
        if deleted_count > 0:
            print(f"✅ CLEANUP COMPLETE: {deleted_count} unauthorized root folder(s) deleted")
            print(f"   Deleted folders: {', '.join(unauthorized_folders)}")
        else:
            print(f"✅ CLEANUP COMPLETE: No unauthorized root folders found to delete")
        
        print(f"   Protected folders remaining at root level: {', '.join(sorted(protected_folders))}")
        print(f"   📂 Contents inside protected folders (ohlc & strategies) remain untouched")
        print(f"{'='*60}")
        
        return True
        
    except Exception as e:
        print(f"[{dev_user_id}]  Critical Error in cleanup: {e}")
        import traceback
        traceback.print_exc()
        return False
    
def sync_dev_investors(dev_user_id):
    """
    Worker: Synchronizes investor strategy folders with developer data.
    
    Reads strategy folders directly from the developer's directory.
    For each investor, checks if invested_with matches any developer strategy folder.
    Creates investor folder: INV_PATH/{investor_id}/{strategy_name}/
    Copies ONLY the pending_orders folder and ONLY limit_orders.json inside it.
    Developer's original files remain untouched.
    
    Supports:
    - Single strategy: "KEY-LEVEL-BREAKOUT"
    - Multiple strategies: "KEY-LEVEL-BREAKOUT, STRUCTURAL-LIQUIDITY-1"
    - With developer ID prefix: "6_KEY-LEVEL-BREAKOUT", "6keylevelbreakout", "6-KEY-LEVEL-BREAKOUT"
    """
    try:
        print(f"\n{'='*60}")
        print(f"🔄 SYNCING INVESTORS FOR DEVELOPER USER ID: {dev_user_id}")
        print(f"{'='*60}")

        # 1. Load required data - Check both possible investor files
        investors_data = {}
        
        # Try FETCHED_INVESTORS first (since that's where your data is)
        if os.path.exists(FETCHED_INVESTORS):
            try:
                with open(FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
                    investors_data = json.load(f)
                print(f"  📂 Loaded investors from FETCHED_INVESTORS")
            except Exception as e:
                print(f"  ⚠️ Error loading FETCHED_INVESTORS: {e}")
        
        # If FETCHED_INVESTORS didn't work or was empty, try INVESTOR_USERS
        if not investors_data and os.path.exists(INVESTOR_USERS):
            try:
                with open(INVESTOR_USERS, 'r', encoding='utf-8') as f:
                    investors_data = json.load(f)
                print(f"  📂 Loaded investors from INVESTOR_USERS")
            except Exception as e:
                print(f"  ⚠️ Error loading INVESTOR_USERS: {e}")
        
        # If still no data, try both files with different structures
        if not investors_data:
            # Try to load FETCHED_INVESTORS as a list or dict
            if os.path.exists(FETCHED_INVESTORS):
                try:
                    with open(FETCHED_INVESTORS, 'r', encoding='utf-8') as f:
                        raw_data = json.load(f)
                        # If it's a list, convert to dict with id as key
                        if isinstance(raw_data, list):
                            for item in raw_data:
                                if 'id' in item:
                                    investors_data[item['id']] = item
                            print(f"  📂 Loaded {len(investors_data)} investors from FETCHED_INVESTORS (list format)")
                        else:
                            investors_data = raw_data
                            print(f"  📂 Loaded investors from FETCHED_INVESTORS (dict format)")
                except Exception as e:
                    print(f"  ⚠️ Error loading FETCHED_INVESTORS: {e}")
        
        if not investors_data:
            return f" [{dev_user_id}]  Error: No investor data found in FETCHED_INVESTORS or INVESTOR_USERS"
        
        # Load developer data
        if not os.path.exists(DEV_USERS):
            return f" [{dev_user_id}]  Error: DEV_USERS file not found"

        with open(DEV_USERS, 'r', encoding='utf-8') as f:
            developers_data = json.load(f)

        # 2. Get developer's folder path
        dev_user_folder = os.path.join(DEV_PATH, str(dev_user_id))
        
        if not os.path.exists(dev_user_folder):
            print(f"   Developer folder not found: {dev_user_folder}")
            return f" [{dev_user_id}]  Developer folder missing"

        # 3. Get ALL strategy folders from developer's directory
        developer_strategies = []
        
        for item in os.listdir(dev_user_folder):
            item_path = os.path.join(dev_user_folder, item)
            
            if os.path.isdir(item_path):
                pending_orders_path = os.path.join(item_path, "pending_orders")
                if os.path.exists(pending_orders_path) and os.path.isdir(pending_orders_path):
                    developer_strategies.append(item)
                    print(f"  📁 Found strategy folder: {item}")

        if not developer_strategies:
            print(f"  ⚠️ No strategy folders found in developer's directory")
            print(f"  📂 Checked: {dev_user_folder}")
            return f" [{dev_user_id}] ⚠️ No strategies found"

        print(f"\n📋 User {dev_user_id} Strategies Found ({len(developer_strategies)}):")
        for strat in developer_strategies:
            print(f"  • {strat}")

        # 4. Helper function to extract developer ID and strategy name
        def extract_dev_id_and_strategy(invested_value):
            """
            Extracts developer ID and strategy name from invested_with value.
            Returns: (dev_id, strategy_name) or (None, None) if no ID found
            """
            invested_value = invested_value.strip()
            import re
            
            # Pattern: number at start, optionally followed by _ or -, then the rest
            match = re.match(r'^(\d+)[_\-]?(.*)$', invested_value)
            
            if match:
                dev_id = match.group(1)
                strategy_part = match.group(2)
                return dev_id, strategy_part
            else:
                return None, invested_value

        # 5. Find investors linked to this developer
        linked_investors = []
        
        print(f"\n🔍 Searching for investors with developer ID: {dev_user_id}")
        
        for inv_user_id, inv_info in investors_data.items():
            # Check both possible field names for invested_with
            invested_with = inv_info.get("INVESTED_WITH") or inv_info.get("invested_with", "").strip()
            
            if not invested_with:
                continue
        
            
            # Split by comma for multiple strategies
            investor_strategies_raw = [s.strip() for s in invested_with.split(",") if s.strip()]
            
            # Process each strategy to extract developer ID and strategy name
            matched_strategies = []
            
            for raw_strategy in investor_strategies_raw:
                extracted_dev_id, extracted_strategy = extract_dev_id_and_strategy(raw_strategy)
                
                # Check if the developer ID matches our target dev_user_id
                if extracted_dev_id == str(dev_user_id):
                    # Now check if the extracted strategy matches any of our developer's strategies
                    for dev_strategy in developer_strategies:
                        if extracted_strategy.lower() == dev_strategy.lower():
                            matched_strategies.append(dev_strategy)
                            break
                    else:
                        print(f"     No matching strategy found for: '{extracted_strategy}'")
            
            if matched_strategies:
                linked_investors.append({
                    "inv_user_id": inv_user_id,
                    "inv_info": inv_info,
                    "matched_strategies": matched_strategies
                })
                print(f"  ✅ Investor {inv_user_id} signed with User {dev_user_id} {dev_strategy} {len(matched_strategies)} strategies")

        # 6. If no investors found, return message
        if not linked_investors:
            print(f"\n  ℹ️  No investors signed with User {dev_user_id}")
            print(f"{'='*60}")
            return f" [{dev_user_id}] 🔘 No investors linked to this developer"

        print(f"\n📊 Found {len(linked_investors)} investor(s) linked to this developer")

        # 7. Process each investor
        total_synced = 0
        synced_summary = []
        
        for link in linked_investors:
            inv_user_id = link["inv_user_id"]
            inv_info = link["inv_info"]
            matched_strategies = link["matched_strategies"]
            
            inv_name = inv_info.get("fullname") or inv_info.get("FULLNAME") or inv_info.get("NAME") or inv_user_id
            inv_server = inv_info.get("SERVER") or inv_info.get("server", "")
            
            print(f"\n┌─{'─'*50}─┐")
            print(f"│  👤 INVESTOR: {inv_name} (ID: {inv_user_id})")
            print(f"│  📋 Server: {inv_server}")
            print(f"│  📋 Matched Strategies: {', '.join(matched_strategies)}")
            print(f"├─{'─'*50}─┤")
            
            # Create investor root folder
            inv_root_path = os.path.join(INV_PATH, str(inv_user_id))
            os.makedirs(inv_root_path, exist_ok=True)
            
            # Track synced strategies for this investor
            investor_synced = []
            
            # Process each matched strategy
            for strategy_name in matched_strategies:
                
                # Source: Developer's strategy folder (READ ONLY - NOT MODIFIED)
                dev_strat_path = os.path.join(dev_user_folder, strategy_name)
                dev_pending_path = os.path.join(dev_strat_path, "pending_orders")
                
                # Destination: Investor's strategy folder
                inv_strat_path = os.path.join(inv_root_path, strategy_name)
                inv_pending_path = os.path.join(inv_strat_path, "pending_orders")
                
                if not os.path.exists(dev_pending_path):
                    print(f"│      Developer does not have pending_orders folder for: {strategy_name}")
                    continue
                
                try:
                    
                    if os.path.exists(inv_strat_path):
                        shutil.rmtree(inv_strat_path)
                    
                    os.makedirs(inv_pending_path, exist_ok=True)
                    
                    dev_limit_orders = os.path.join(dev_pending_path, "limit_orders.json")
                    inv_limit_orders = os.path.join(inv_pending_path, "limit_orders.json")
                    
                    if os.path.exists(dev_limit_orders):
                        shutil.copy2(dev_limit_orders, inv_limit_orders)
                        
                        other_json_files = []
                        for file in os.listdir(dev_pending_path):
                            if file.endswith('.json') and file != "limit_orders.json":
                                other_json_files.append(file)
                        
                    else:
                        print(f"│     ⚠️  No limit_orders.json found in developer's pending_orders")
                    
                    investor_synced.append(strategy_name)
                    total_synced += 1
                    print(f"│     ✅ Strategy synced successfully")
                    
                except Exception as e:
                    print(f"│      Sync failed: {e}")
                    import traceback
                    traceback.print_exc()
            
            if investor_synced:
                synced_summary.append(f"{inv_name}({len(investor_synced)} strat)")
                print(f"│  \n│  ✅ Investor complete: {len(investor_synced)} strategies synced")
            else:
                print(f"│  ⚠️ No strategies synced for this investor")
            
            print(f"└─{'─'*50}─┘")
        
        print(f"\n{'='*60}")
        if total_synced > 0:
            print(f"✅ SYNC COMPLETE: {total_synced} strategies synced for {len(linked_investors)} investor(s)")
            print(f"   Investors: {', '.join(synced_summary)}")
            print(f"   📂 Structure: INV_PATH/investor_id/strategy_name/pending_orders/limit_orders.json")
            print(f"   🔒 Developer files preserved at: {dev_user_folder}")
            print(f"{'='*60}")
            return f" [{dev_user_id}] ✅ Sync complete. {total_synced} strategies synced"
        else:
            print(f"⚠️ No strategies were synced")
            print(f"{'='*60}")
            return f" [{dev_user_id}] ⚠️ No strategies synced"

    except Exception as e:
        error_msg = f" [{dev_user_id}]  Sync Error: {e}"
        print(f"\n{error_msg}")
        print(f"{'='*60}")
        import traceback
        traceback.print_exc()
        return error_msg

def process_single_developer_pipeline(user_id, max_symbols_parallel=5):
    """
    Orchestrator: Runs the full suite of tasks for one developer sequentially.
    This allows multiprocessing to happen at the 'Account Level'.
    """
    try:  
        sync_dev_investors(user_id)
        
        return f"[User {user_id}] Pipeline completed successfully"
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"--- [User {user_id}] PIPELINE FAILED: {e} ---"

def process_single_developer_pipeline_(user_id, max_symbols_parallel=5):
    """
    Orchestrator: Runs the full suite of tasks for one developer sequentially.
    This allows multiprocessing to happen at the 'Account Level'.
    """
    try:  
        # Step 1: Data Sync - pass user_id
        res_candles = copy_full_candle_data(user_id)
        print(res_candles)
        
        # Step 2: HH/LL Analysis with symbol-level multiprocessing - pass user_id
        res_hhll = swing_points(user_id, max_symbols_parallel)
        print(res_hhll)
        
        # Step 3: POI - pass user_id
        res_poi = entry_point_of_interest(user_id)
        
        # Step 4: Entries Confirmation - pass user_id
        res_entries = entries_confirmation(user_id)
        
        # Step 5: Cleanup - pass user_id
        res_clean = clear_unathorized_entries_folders(user_id)
        
        # Step 6: Investor Sync
        res_sync = sync_dev_investors(user_id)
        
        return f"[User {user_id}] Pipeline completed successfully"
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"--- [User {user_id}] PIPELINE FAILED: {e} ---"

def main():
    
    # Parse command line arguments
    run_as_loop = False
    loop_interval = 0  # Default 5 minutes between loops
    max_loops = None  # None means infinite
    
    # Check for command line arguments
    for arg in sys.argv[1:]:
        if arg.startswith('--loop='):
            loop_value = arg.split('=')[1].lower()
            run_as_loop = loop_value in ['true', 'yes', '1', 'on']
        elif arg.startswith('--interval='):
            try:
                loop_interval = int(arg.split('=')[1])
            except ValueError:
                print(f"Invalid interval value: {arg.split('=')[1]}. Using default 300 seconds.")
        elif arg.startswith('--max-loops='):
            try:
                max_loops = int(arg.split('=')[1])
            except ValueError:
                print(f"Invalid max-loops value: {arg.split('=')[1]}. Running infinite loops.")
    
    print("\n" + "="*60)
    print("                 SYNAPSE DATA PIPELINE")
    print("="*60)
    print(f"  Loop Mode: {'ENABLED' if run_as_loop else 'DISABLED'}")
    if run_as_loop:
        print(f"  Interval: {loop_interval}s")
        if max_loops:
            print(f"  Max Loops: {max_loops}")
        else:
            print("  Max Loops: Infinite")
    print("="*60 + "\n")
    
    loop_count = 0
    
    while True:
        loop_count += 1
        
        if run_as_loop:
            print("\n" + "="*60)
            print(f"LOOP #{loop_count} STARTED")
            print("="*60)
        
        # Load developers dictionary
        dev_dict = load_developers_dictionary()
        if not dev_dict:
            print("No developers to process.")
            if not run_as_loop:
                return
            else:
                print(f"Waiting {loop_interval} seconds before retrying...")
                time.sleep(loop_interval)
                continue
        
        user_ids = sorted(dev_dict.keys())
        cores = cpu_count()
        
        # You can adjust this value - number of symbols to process in parallel per broker
        MAX_SYMBOLS_PARALLEL = 5  # Change this to control concurrency per broker
        
        print(f"--- STARTING ACCOUNT-LEVEL MULTIPROCESSING ---")
        print(f"Cores: {cores} | Total Developers: {len(user_ids)}")
        print(f"Symbols per broker processed in parallel: {MAX_SYMBOLS_PARALLEL}")

        # Use multiprocessing Pool for broker-level parallelism
        with Pool(processes=cores) as pool:
            # Pass max_symbols_parallel to each broker process
            from functools import partial
            process_func = partial(process_single_developer_pipeline, max_symbols_parallel=MAX_SYMBOLS_PARALLEL)
            final_results = pool.map(process_func, user_ids)
            
            # Print summaries as they finish
            for report in final_results:
                print(report)

        print("\n[SUCCESS] All developer pipelines completed.")
        
        # Check loop conditions
        if not run_as_loop:
            # Single execution - exit
            print("Single execution completed. Exiting...")
            break
        
        # Check max loops
        if max_loops and loop_count >= max_loops:
            print(f"Maximum loops ({max_loops}) reached. Exiting...")
            break
        
        # Wait before next iteration
        print(f"Waiting {loop_interval} seconds before next loop...")
        time.sleep(loop_interval)

if __name__ == "__main__":
    main()


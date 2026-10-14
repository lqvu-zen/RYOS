# RYOS behaviour map

`ARCHITECTURE.md`, `adr/` and `CLAUDE.md` say how RYOS is built. This file says
**what must keep working, and everywhere it shows up.** Most behaviours appear in
several places at once: normal rows, compact rows, favourite chips, the maximised
detail pane, select mode, scripts and pipelines, the window and the command line.
A change that reaches one place breaks the others unseen. (That is how compact mode
broke three times, select mode missed pipelines, and Quick Run lost "add as a new
script".)

Each entry is one line the user would recognise, **every surface** it appears on,
and the test that guards it, or **untested**.

## How to use it

- **Before you change an area, read its entries.** Check each surface listed, not
  only the one you are working on.
- **A fix adds or updates its entry and its test.** Put the issue number in the
  behaviour text, e.g. "(#27)".
- **A feature adds its entries** in the same change, with the surfaces it reaches.
- **Test names are exact.** Format: `test_ryos::<Class>::<test>` (a unit test in
  `tests/test_ryos.py`), `qt_smoke::<check>` (a check in `tests/qt_smoke.py`),
  `session_smoke::<step>` (a step in `tests/session_smoke.py`). A bare class name
  means every test in that class applies. `tests/test_cli.py`, `test_headless.py`,
  `test_agenttools.py` and `test_mcpserver.py` are cited the same way.
  `release_check::<case>` is a case of `tests/release_check.py`, the release gate
  that runs on the built downloads (`release-ryos`), not in CI.
- **A smoke check usually opens one layout.** Where a check covers only some of the
  surfaces, the Guarded-by cell says which, e.g. "(N only)". The surfaces it does not
  name are unguarded, and the last section lists them.

## Surfaces

| Code | Surface |
| --- | --- |
| **N** | Normal (full-size) rows in the list |
| **C** | Compact rows (Options > Cards > Compact cards) |
| **F** | Favourite chips (the Favorites strip) |
| **A** | The All tab |
| **D** | The maximised layout: list on the left, detail pane, rail and Activity bar on the right |
| **S** | Select mode |
| **Sc** | Scripts |
| **P** | Pipelines (when an entry names both, it applies to both) |
| **R** | The Running list, the status bar and the Activity bar's running lines |
| **W** | The window as a whole (menus, dialogs, header, output panel) |
| **CLI** | `ryos-cli` / `ryos <command>`, headless |
| **MCP** | `ryos mcp`, what an AI agent sees |
| **T** | The tray icon, its menu and its tooltip |

---

## 1. Rows and cards

| Behaviour | Surfaces | Guarded by |
| --- | --- | --- |
| **RC-01** A row shows its name, kind tag (PYTHON, BATCH, PIPELINE...), file or steps, how the last run went and the Run button. | N C F D · Sc P | `test_ryos::TestCardSecondLine::test_path_is_relative_inside_the_base_folder`, `test_ryos::TestCardSecondLine::test_steps_summary`, `qt_smoke::check_cards` |
| **RC-02** The last run's time reads to the minute. | N D · Sc P | `test_ryos::TestCardSecondLine::test_last_run_to_the_minute` |
| **RC-03** Edit, Run-with and the star appear when you point at a row; Run does not move when they appear; the gold star of a favourite is always shown. | N · Sc P | `qt_smoke::check_cards` (N only for the hover part) |
| **RC-04** Columns line up: every row has the same cells at the same x, Scripts and Pipelines alike (#3, #7). | N C · Sc P | `qt_smoke::check_cards` (loops N and C) |
| **RC-05** On compact rows the kind tag is one column, and the empty outcome slot beside Run is not drawn as an empty box (#10, #7). | C · Sc P | `qt_smoke::check_cards` |
| **RC-06** Run is a round button of a fixed size, whatever the card size (small, medium, large). | N C F | `qt_smoke::check_cards` |
| **RC-07** The Run button's ink is legible on every theme and every state. | N C F D | `test_ryos::TestRunFillInk`, `test_ryos::TestRunButtonInkIsWired`, `test_ryos::TestDisabledState` |
| **RC-08** Disabled buttons look different from enabled ones, on every theme (#7). | W | `qt_smoke::check_disabled_button_differs`, `test_ryos::TestDisabledState` |
| **RC-09** After a failed run, Run turns red with a retry arrow; pressing it runs again. | N C F D · Sc P | `session_smoke::step_failure_and_retry`, `qt_smoke::check_cards`, `test_ryos::TestStopAndLiveStatus::test_live_statuses` |
| **RC-10** While a row's own run is going its Run is Stop; pressing it stops that run and starts no second copy. | N C F D · Sc P | `qt_smoke::check_run_becomes_stop` (N only), `test_ryos::TestStopAndLiveStatus::test_run_becomes_stop_only_for_an_items_own_run` |
| **RC-11** A script running only as a pipeline's step keeps its Run button (stopping it there would stop the pipeline), and stopping one row's run does not touch the pipeline's. | N C F D · Sc | `qt_smoke::check_run_becomes_stop` |
| **RC-12** A running row says Running, "now" rather than "last run" (#13), in every place the item shows. | N C F D · Sc P | `test_ryos::TestStopAndLiveStatus::test_badges_for_live_states`, `test_ryos::TestStopAndLiveStatus::test_a_dot_chip_says_now_not_last_run_for_live_states`, `session_smoke::step_stop`, `session_smoke::step_favourite_and_delete` |
| **RC-13** A stopped run reads "Stopped" everywhere (row, activity, detail), and is not offered a retry. | N C F D R · Sc P | `test_ryos::TestAStoppedRunIsStopped` |
| **RC-14** Long names, paths and parameters never push Run out of view, add a sideways scrollbar or widen the window. | N C | `qt_smoke::check_long_text_fits` |
| **RC-15** A name too long for its row scrolls like a marquee; one that fits does not; hovering pauses it. | N C | `qt_smoke::check_scrolling_label`, `test_ryos::TestMarquee` |
| **RC-16** Settings badges (asks for parameters, SCHEDULED, outside folder) show on full rows only; compact rows drop them, except the outside-folder warning. | N C · Sc P | `test_ryos::TestFileDropAndCardDetails::test_badges`, `qt_smoke::check_badges_banner_previews` |
| **RC-17** A compact row shows its path and parameters in a hover preview when the option is on, and never on a full-size row. | C · Sc P | `qt_smoke::check_badges_banner_previews`, `test_ryos::TestFileDropAndCardDetails::test_preview_rows` |
| **RC-18** The hover preview never takes clicks: on a compact row, the star and Run are what is under their own centres (#28). | C F · Sc P | `qt_smoke::check_badges_banner_previews` |
| **RC-19** A pipeline row's steps popup lists its steps, marks parallel steps and shows overrides. | N C · P | `qt_smoke::check_badges_banner_previews`, `test_ryos::TestCardSecondLine::test_steps_summary` |
| **RC-20** A row's right-click menu offers, in order: edit, run with parameters, favourite, highlight, move, schedule, history, clone, copy, copy to, delete. A pipeline's menu leads with Edit. | N C F D (its three dots) · Sc P | `test_ryos::TestCardMenu::test_script_menu_order`, `test_ryos::TestCardMenu::test_pipeline_menu_leads_with_edit`, `qt_smoke::check_context_menus` |
| **RC-21** Move Up / Move to Top are off on the first row and Move Down on the last; Move swaps with the neighbour in its own section. | N C F · Sc P | `test_ryos::TestCardMenu::test_moves_disable_at_the_ends`, `test_ryos::TestCardMenu::test_move_up_and_to_top`, `qt_smoke::check_context_menus`, `qt_smoke::check_sections_and_favorites` |
| **RC-22** Highlight colours a row's name; the menu marks the current one; every colour is legible on every theme. | N C F D · Sc P | `test_ryos::TestCardMenu::test_highlight_submenu_marks_the_current_colour`, `test_ryos::TestHighlightPalette`, `test_ryos::TestReadableHighlight`, `qt_smoke::check_context_menus` |
| **RC-23** The star button and the menu both add and remove a favourite, and the menu's wording follows the state. | N C F D · Sc P | `test_ryos::TestCardMenu::test_favorite_label_follows_state`, `qt_smoke::check_context_menus` |
| **RC-24** Clone makes "name (copy)" in the same group with everything that defines how it runs, its star, highlight, steps and presets, but not its run history. | N C F D · Sc P | `test_ryos::TestCardMenu::test_clone_keeps_how_a_script_runs`, `test_ryos::TestCloneCarriesEverything`, `qt_smoke::check_context_menus` |
| **RC-25** Delete asks first and names the item; deleting a script a pipeline uses names those pipelines. | N C F D · Sc P | `test_ryos::TestCardMenu::test_delete_prompts_name_the_item`, `test_ryos::TestDeletePromptsNamePipelines`, `session_smoke::step_favourite_and_delete`, `qt_smoke::check_context_menus` |
| **RC-26** Deleting leaves nothing behind: steps, presets and schedule go; run history stays. | Sc P | `test_ryos::TestDeletesLeaveNothingBehind`, `test_ryos::TestOrphanMigration` |
| **RC-27** Every menu entry has an icon from the one icon set; no button or menu text carries an emoji or symbol glyph. | W | `test_ryos::TestMenusUseTheIconSet`, `qt_smoke::check_one_icon_set` |
| **RC-28** A tick box draws a tick and a chosen radio button a dot, on every theme. | W | `qt_smoke::check_ticks_are_drawn` |
| **RC-29** Keyboard: Down from the search box reaches the first row, arrows move, End stays on the last, Enter runs, F2 edits, the Menu key opens the menu; the row the keyboard is on is marked, a clicked one is not. | N · Sc P | `qt_smoke::check_keyboard_through_the_list` (N only) |
| **RC-30** Ctrl+C on a row copies it. | N · Sc P | `qt_smoke::check_copy_paste_between_groups` (N only) |
| **RC-31** A row announces its name and key hints to a screen reader; row buttons and the + pill have names. | N · Sc P | `qt_smoke::check_keyboard_through_the_list`, `qt_smoke::check_review_fixes` |
| **RC-32** Clicking Run leaves no focus ring on the button; Tab still reaches the rows and header buttons. | N | `qt_smoke::check_focus_starts_in_search` |
| **RC-33** A parameter drop-down on a row shows only when the script has presets, starts on the script's own parameters, and Run passes what is chosen (see section 13). | N C F · Sc | `qt_smoke::check_run_with_params_and_new_pipeline`, `test_ryos::TestRunParams`, `test_ryos::TestParamOptions` |
| **RC-34** A row's preset chip shows the preset Run will use and lets you choose another from a menu. | N F · Sc | `qt_smoke::check_strip_and_preset` |
| **RC-35** The pane's Edit, Run, star and three dots do exactly what the row's own buttons do. | D · Sc P | `qt_smoke::check_maximised_layout` (Run and Retry only) |
| **RC-36** A group name with "&" shows the "&" on its tab and in menus naming the group. | W | `qt_smoke::check_ampersands_show` |

## 2. Favourites

| Behaviour | Surfaces | Guarded by |
| --- | --- | --- |
| **FV-01** Starred items show in a Favorites strip of small chips, each with its own Run button; the strip wraps when narrow. | F N C A · Sc P | `qt_smoke::check_sections_and_favorites`, `qt_smoke::check_strip_and_preset`, `test_ryos::TestSections::test_split` |
| **FV-02** A chip's Run button takes clicks, in compact mode too (#28). | F C · Sc P | `qt_smoke::check_badges_banner_previews` |
| **FV-03** A chip has a fixed size and its Run button a fixed size; its star shows without hovering. | F | `qt_smoke::check_cards` |
| **FV-04** A starred item is in Favorites and also in its own section; the run state and last outcome agree in both cards. | F N C · Sc P | `session_smoke::step_favourite_and_delete`, `qt_smoke::check_sections_and_favorites` |
| **FV-05** Starring puts the item in Favorites at once; unstarring takes it out. | F N C D · Sc P | `qt_smoke::check_sections_and_favorites`, `qt_smoke::check_context_menus`, `session_smoke::step_favourite_and_delete` |
| **FV-06** Move Up / Down in Favorites swaps with the next favourite; dragging a chip reorders within Favorites, in a group and in the All view. | F A · Sc P | `test_ryos::TestDragDropRules::test_a_favorite_reorders_within_its_own_group`, `test_ryos::TestDragDropRules::test_a_favorite_reorders_even_in_the_all_view`, `qt_smoke::check_sections_and_favorites`, `qt_smoke::check_strip_and_preset` |
| **FV-07** The drop line is shown for a favourite in the All view and hidden for a normal row there. | F A | `test_ryos::TestDragDropRules::test_indicator_shown_for_a_favorite_in_the_all_view`, `test_ryos::TestDragDropRules::test_indicator_hidden_for_a_normal_card_in_the_all_view` |
| **FV-08** A favourite's copy in the strip has no select box; the original row does. | F S | `qt_smoke::check_sections_and_favorites` |
| **FV-09** A copy or clone keeps the star and highlight of the original. | N C F · Sc P | `test_ryos::TestCopyBetweenGroups::test_copies_and_clones_keep_the_star_and_highlight`, `test_ryos::TestCloneCarriesEverything::test_clone_group_carries_script_colour_and_favourite`, `test_ryos::TestCloneCarriesEverything::test_clone_pipeline_carries_colour_and_favourite` |
| **FV-10** Sections (Favorites, Pipelines, Scripts) fold with their header; the fold is remembered per group for the session, survives a reload, and is shared with the All tab. | N C A | `test_ryos::TestSections::test_collapse_state`, `qt_smoke::check_sections_and_favorites`, `qt_smoke::check_all_tab` |
| **FV-11** An empty section says so, in words. | N C A | `test_ryos::TestSections::test_every_section_has_words`, `qt_smoke::check_sections_and_favorites` |
| **FV-12** Search finds a favourite in both its chip and its row. | F N | `qt_smoke::check_sections_and_favorites` |
| **FV-13** The detail pane's star adds or removes the favourite. | D · Sc P | **untested** |

## 3. Groups and base folders

| Behaviour | Surfaces | Guarded by |
| --- | --- | --- |
| **GR-01** Clicking a pill switches group; the dashed + makes a group and brings it to the front. | W | `qt_smoke::check_group_management`, `session_smoke::step_groups_and_scripts` |
| **GR-02** A new group needs a name that is not blank and not a duplicate (after trimming). | W | `test_ryos::TestGroupCrudRules::test_a_blank_name_is_rejected`, `test_ryos::TestGroupCrudRules::test_a_duplicate_is_caught_after_trimming`, `qt_smoke::check_small_dialogs` |
| **GR-03** Rename refuses an existing name; renaming the open group keeps it open; renaming from the All view stays there. | W A | `test_ryos::TestGroupMenuRules::test_rename_clash_is_a_problem`, `test_ryos::TestGroupCrudRules::test_renaming_the_open_group_follows_it`, `test_ryos::TestGroupCrudRules::test_renaming_while_in_the_all_view_stays_there`, `qt_smoke::check_context_menus` |
| **GR-04** Delete group asks, removes its items, and falls back to the first group, or to All when it was the last. | W A | `test_ryos::TestGroupCrudRules::test_deleting_the_open_group_falls_back_to_the_first`, `test_ryos::TestGroupCrudRules::test_deleting_the_last_group_falls_back_to_the_all_view`, `qt_smoke::check_context_menus` |
| **GR-05** Clone group deep-copies scripts, pipelines, steps, presets, colour, favourite and environment, but not run history. | W · Sc P | `test_ryos::TestScriptDBGroups::test_clone_group_deep_copies`, `test_ryos::TestCloneCarriesEverything`, `qt_smoke::check_context_menus` |
| **GR-06** A group clone is named "X (copy)", then "X (copy 2)", skipping names that exist. | W | `test_ryos::TestGroupCrudRules::test_the_first_copy_is_unnumbered`, `test_ryos::TestGroupCrudRules::test_numbering_skips_what_exists` |
| **GR-07** Dragging a pill reorders groups, Ungrouped included, and the order is stored. | W | `qt_smoke::check_group_management` |
| **GR-08** Tab pills keep rounded corners (#11). | W | `qt_smoke::check_pill_corners` |
| **GR-09** The group menu offers Rename, Paste, Clone, Base folder, Export, Make all in this group available to agents… (where agents are offered), Delete; the Ungrouped tab and All offer none. | W A | `qt_smoke::check_context_menus`, `qt_smoke::check_all_tab`, `test_ryos::TestCardMenu::test_group_menu_offers_agents_only_where_offered` |
| **GR-10** Setting or moving a group's base folder asks before remapping paths, and reports what it left alone; clearing it always confirms. | W · Sc | `test_ryos::TestGroupMenuRules::test_base_dir_move_confirms_the_remap`, `test_ryos::TestGroupMenuRules::test_base_dir_clear_always_confirms`, `test_ryos::TestBaseDirMovesWorkDir`, `qt_smoke::check_context_menus` |
| **GR-11** Each group page shows a banner with its base folder, or a hint to set one; Ungrouped has none; clicking it opens the base-folder dialog. | W | `qt_smoke::check_badges_banner_previews`, `test_ryos::TestFileDropAndCardDetails::test_banner` |
| **GR-12** The All tab shows every group under its heading; the empty message names the Add button; an "Other" heading is not shown when only ungrouped items exist. | A | `test_ryos::TestAllViewAndLastGroup`, `test_ryos::TestSections`, `qt_smoke::check_all_tab` |
| **GR-13** The last group, or All, is reopened at start; with the option off it opens on the first group and does not overwrite the remembered one. | W A | `qt_smoke::check_all_tab`, `test_ryos::TestAllViewAndLastGroup::test_remember_group`, `session_smoke::step_restart` |
| **GR-14** Dragging a row onto another pill moves it; the file follows into the new base folder only when it is there, otherwise it keeps its file and says it is outside. | N C F · Sc P | `test_ryos::TestApplyDrop`, `qt_smoke::check_drag_and_drop` (N only) |
| **GR-15** Dragging within a panel reorders, with a line showing the landing place; a 3-pixel twitch is not a drag; a drop on a card's own tab, on All or with a malformed payload changes nothing. | N A · Sc P | `test_ryos::TestDragDropRules`, `test_ryos::TestComputeInsertion`, `qt_smoke::check_drag_and_drop`, `qt_smoke::check_all_tab` |
| **GR-16** A normal row cannot be reordered from the All view; a favourite can. | A | `test_ryos::TestDragDropRules::test_a_normal_card_cannot_reorder_in_the_all_view` |
| **GR-17** A move that makes a script run a different file takes it away from agents; one that keeps the file keeps it. | N C · Sc MCP | `test_ryos::TestApplyDrop::test_a_move_that_changes_the_file_withdraws_it_from_agents`, `test_ryos::TestApplyDrop::test_a_move_that_keeps_the_file_keeps_it_for_agents` |
| **GR-18** Copy to / Copy + Paste put a copy in another group with its parameters, interpreter, environment, working folder, presets, launcher flag, star and highlight; the original stays. | N C F D · Sc | `test_ryos::TestCopyBetweenGroups::test_a_script_copies_with_how_it_runs_and_its_presets`, `test_ryos::TestCopyBetweenGroups::test_copies_and_clones_keep_the_star_and_highlight`, `qt_smoke::check_copy_paste_between_groups` |
| **GR-19** A copied pipeline brings the scripts its steps run; if the group already has a script that runs identically, it is reused rather than duplicated. | N C F D · P | `test_ryos::TestCopyBetweenGroups::test_a_pipeline_brings_its_scripts_and_keeps_its_steps`, `test_ryos::TestCopyBetweenGroups::test_an_exact_twin_is_reused`, `qt_smoke::check_copy_paste_between_groups` |
| **GR-20** Pasting into the item's own group makes a copy beside it, named "(copy)". | N C F D | `test_ryos::TestCopyBetweenGroups::test_pasting_into_its_own_group_is_a_copy_beside_it` |
| **GR-21** Into a group with a base folder, a copy's path and working folder follow into it, each decided on its own, and only when both groups have a folder and the target file exists. | N C F D · Sc | `test_ryos::TestCopyBetweenGroups::test_path_and_work_dir_follow_into_the_other_groups_folder`, `test_ryos::TestCopyBetweenGroups::test_path_and_work_dir_are_decided_independently`, `test_ryos::TestCopyBetweenGroups::test_nothing_is_repointed_without_both_folders`, `test_ryos::TestCopyBetweenGroups::test_a_missing_target_keeps_the_original` |
| **GR-22** Paste is greyed until something is copied, and names what it will paste. | W | `test_ryos::TestCopyBetweenGroups::test_the_menus`, `qt_smoke::check_copy_paste_between_groups` |
| **GR-23** A copy that runs another file loses "Available to agents" and the status line says so. | W · Sc P MCP | `test_ryos::TestCopyBetweenGroups::test_agents_lose_a_copy_that_runs_another_file`, `test_ryos::TestCopyBetweenGroups::test_agents_lose_a_pipeline_copy_whose_steps_run_other_files` |
| **GR-24** A copy leaves the schedule and run history with the original. | N C F D · Sc P | `test_ryos::TestCloneCarriesEverything::test_clone_group_leaves_run_history_behind` (history only). Schedule: **untested** |
| **GR-25** Ctrl+V on a row in another group pastes what was copied into that row's group. | N C · Sc P | `session_smoke::step_keyboard_and_menu` |
| **GR-26** A script outside its group's base folder (its file or its working folder) gets an OUTSIDE FOLDER tag on a full row, with the base folder named in the tooltip. | N D · Sc | `test_ryos::TestBaseFolder`, `qt_smoke::check_badges_banner_previews` |
| **GR-27** On a compact row the outside tag is a small warning icon whose words stay in the tooltip and for screen readers; favourite chips show none. | C F · Sc P | `test_ryos::TestBaseFolder::test_compact_rows_keep_the_warning_and_chips_show_none`, `test_ryos::TestOutsideWarning::test_the_compact_icon`, `qt_smoke::check_outside_warning`, `qt_smoke::check_badges_banner_previews` |
| **GR-28** A pipeline gets the tag when one of its steps is outside, and the tooltip names the step. | N C D · P | `test_ryos::TestBaseFolderNotes::test_a_pipeline_notes_only_the_outside_step`, `qt_smoke::check_badges_banner_previews` |
| **GR-29** The detail pane has a row for the outside folder only when it is outside. | D · Sc | `test_ryos::TestBaseFolder::test_the_detail_row_appears_only_when_outside` |
| **GR-30** Running an outside script or pipeline from the window asks first (Run anyway / Cancel); Cancel runs nothing; "Don't warn me again", or the Options box, stops the question but keeps the tag and note. | N C F D S · Sc P | `qt_smoke::check_outside_warning` (window rows, and Run selected), `test_ryos::TestOutsideWarning::test_when_to_warn`, `test_ryos::TestOutsideWarning::test_an_answer`, `test_ryos::TestOutsideWarning::test_on_by_default_with_a_field_in_options` |
| **GR-31** Run selected on an outside pipeline asks, and starts it after "Run anyway" (#27). | S · P | `qt_smoke::check_outside_warning` |
| **GR-32** The output of a run started from the window begins with a one-line note naming what is outside; a pipeline notes only its outside step; nothing is added when nothing is outside. | N C F D · Sc P | `test_ryos::TestBaseFolderNotes`, `session_smoke::step_outside_note` |
| **GR-33** Runs from the command line, agents or a schedule add no outside note and never ask. | CLI MCP | `test_cli::TestRun::test_outside_the_base_folder_adds_nothing_to_the_output`, `test_headless::TestRunningAScript::test_a_script_outside_its_base_folder_gets_no_note`. `session_smoke::step_scheduled_outside` (a scheduled run never asks). **Failing:** a scheduled run of an outside script still opens its output with the outside-folder note; the check reports it as a known bug |
| **GR-34** Dropping files on the window adds them to the group on screen; files outside the group's base folder are skipped and named in a warning; a drop on All goes to Ungrouped; a card drag is not a file drop. | W A | `qt_smoke::check_file_drop`, `test_ryos::TestFileDropAndCardDetails::test_drop_plan` |
| **GR-35** A group tab's "Make all in this group available to agents…" lists only the new ones and asks, worded as the command line; nothing new or an empty group says so; it rebuilds no rows. | W · Sc P | `session_smoke::step_agents_for_a_group`, `test_ryos::TestGroupExposure` |

## 4. Select mode

| Behaviour | Surfaces | Guarded by |
| --- | --- | --- |
| **SM-01** Options > Select scripts or pipelines shows a tick box on every script **and every pipeline** row, and a bar; favourite chips get none (#27). | S N · Sc P | `qt_smoke::check_select_mode` (N only), `qt_smoke::check_sections_and_favorites`, `test_ryos::TestSelectionTakesPipelines` |
| **SM-02** A click on a row, not on its buttons, ticks it; a second click unticks; a button click does not tick (#27). | S N · Sc P | `qt_smoke::check_select_mode` (N only) |
| **SM-03** A drag is not a click: it does not tick. | S N | `qt_smoke::check_select_mode` |
| **SM-04** Space ticks the row in select mode, script and pipeline; outside select mode a click only chooses the row. | S N · Sc P | `qt_smoke::check_keyboard_through_the_list` |
| **SM-05** The bar counts scripts and pipelines in words and starts with a hint; Select All / Deselect All ticks everything on screen. | S · Sc P | `test_ryos::TestSelection::test_bar_text`, `test_ryos::TestSelection::test_select_all_label_and_target`, `test_ryos::TestSelectionTakesPipelines::test_wording_names_scripts_and_pipelines`, `test_ryos::TestSelectionTakesPipelines::test_count_words`, `qt_smoke::check_select_mode` |
| **SM-06** Run selected starts every ticked item; a pipeline is one job against the parallel-job cap; past the cap one notice gives the counts and the selection stays so the rest can be retried (#27). | S · Sc P | `test_ryos::TestSelectionTakesPipelines::test_a_pipeline_is_one_job_against_the_cap`, `test_ryos::TestSelection::test_past_the_cap_one_notice_with_counts`, `test_ryos::TestSelectionTakesPipelines::test_run_plan_counts_each_kind`, `qt_smoke::check_select_mode` |
| **SM-07** The status line after Run selected counts what started ("Started 3 scripts and 1 pipeline."). | S · Sc P | `qt_smoke::check_select_mode`, `session_smoke::step_quick_run_search_select` |
| **SM-08** Run selected with nothing ticked explains itself; a missing script is refused visibly. | S | `test_ryos::TestSelection::test_nothing_selected_explains`, `qt_smoke::check_select_mode` |
| **SM-09** Delete selected asks once, naming how many scripts and pipelines; declining deletes nothing; afterwards the mode is left. | S · Sc P | `test_ryos::TestSelectionTakesPipelines::test_delete_prompt_counts_both_kinds_in_one_question`, `test_ryos::TestSelection::test_delete_prompt`, `qt_smoke::check_select_mode` |
| **SM-10** Switching tabs re-scopes the selection; in All, select mode offers every group's rows. | S A | `qt_smoke::check_select_mode`, `qt_smoke::check_all_tab` |
| **SM-11** The session test ticks a pipeline row by clicking it and runs it. | S N · P | `session_smoke::step_quick_run_search_select` |
| **SM-12** The menu entry flips to "Cancel select" while the mode is on. | S W | `session_smoke::step_keyboard_and_menu` |
| **SM-13** Select mode on compact rows, on the maximised list and with a search active: ticking, Select All, Run selected. | S C D | `qt_smoke::check_select_bar_fits` (ticking and Select All on C and D, both builds); Run selected and Delete on C/D, and a search active: **untested** |
| **SM-14** Make available / unavailable to agents act on every ticked script and pipeline: on lists only what changes and asks once, off doesn't ask; ticks stay; hidden without agents. | S N C · Sc P | `session_smoke::step_agents_for_a_group`, `test_ryos::TestGroupExposure` |
| **SM-15** The select bar stays readable: every button's label whole and the count on one line, at the 480 px minimum, at 540 and in the maximised list, on full and compact rows, with and without agents. The count sits above the buttons, which wrap onto more lines rather than clip (2.3.1 release test). | S N C D · W | `qt_smoke::check_select_bar_fits`, `qt_smoke::check_output_panel` (minimum width) |
| **SM-16** Starring or unstarring a row in select mode, or maximising the window with full rows, leaves select mode and drops the ticks (known since 2.3.0: every reload does). | S N D · Sc P | **untested (known)** |

## 5. Quick Run

| Behaviour | Surfaces | Guarded by |
| --- | --- | --- |
| **QR-01** A group with a base folder gets a Quick Run bar (when the option is on). | W | `qt_smoke::check_quick_run` |
| **QR-02** Typing a name suggests matching files from the folder and its subfolders; the best match is pre-selected; Up/Down move and stop at the ends rather than wrapping. | W | `test_ryos::TestQuickRunBarRules::test_movement_clamps_rather_than_wraps`, `test_ryos::TestQuickRunBarRules::test_a_name_is_searched_for`, `test_ryos::TestQuickRunRanking`, `qt_smoke::check_quick_run` |
| **QR-03** Tab fills in the pick and leaves room for parameters; typing parameters hides suggestions; Esc closes one layer at a time. | W | `test_ryos::TestQuickRunBarRules::test_tab_leaves_room_for_parameters`, `test_ryos::TestQuickRunBarRules::test_escape_closes_one_layer_at_a_time`, `qt_smoke::check_quick_run` |
| **QR-04** The "indexing" placeholder is never accepted as a file. | W | `test_ryos::TestQuickRunBarRules::test_the_indexing_placeholder_is_never_accepted`, `qt_smoke::check_quick_run` |
| **QR-05** Enter runs a unique match; several matches ask which; no match says why. | W | `test_ryos::TestQuickRunSubmit::test_a_unique_match_runs`, `test_ryos::TestQuickRunSubmit::test_several_matches_ask_which`, `test_ryos::TestQuickRunSubmit::test_no_match_says_why`, `qt_smoke::check_quick_run` |
| **QR-06** A file that is not a script yet is added to the group as one, with the typed parameters; a known file is reused, not added twice; the same file in another group is a separate script. | W · Sc | `test_ryos::TestQuickRunSubmit::test_a_new_path_is_registered_with_its_parameters`, `test_ryos::TestQuickRunSubmit::test_a_known_path_is_reused_not_duplicated`, `test_ryos::TestQuickRunSubmit::test_the_same_file_in_another_group_is_a_separate_script`, `qt_smoke::check_quick_run`, `session_smoke::step_quick_run_search_select` |
| **QR-07** Untyped parameters leave the saved ones alone; typed ones win and are remembered once as a preset; a reused script keeps its launcher flag. | W · Sc | `test_ryos::TestQuickRunSubmit::test_untyped_parameters_leave_the_saved_ones_alone`, `test_ryos::TestQuickRunSubmit::test_typed_parameters_win_and_are_remembered_once`, `test_ryos::TestQuickRunSubmit::test_reusing_a_script_keeps_its_launcher_flag` |
| **QR-08** A Quick Run of a new file shows its row at once, already running, in the compact list, the normal list, the maximised list and the All tab (#30). | N C D A · Sc | `qt_smoke::check_quick_run_shows_new_row`, `test_ryos::TestQuickRunSubmit::test_a_new_script_needs_the_list_refreshed`, `test_ryos::TestQuickRunSubmit::test_a_shown_script_run_as_saved_does_not`, `test_ryos::TestQuickRunSubmit::test_a_script_registered_elsewhere_but_not_shown_is_refreshed`, `session_smoke::step_quick_run_search_select` |
| **QR-09** Typed parameters refresh the row's parameter drop-down. | N C F · Sc | `test_ryos::TestQuickRunSubmit::test_typed_parameters_refresh_the_drop_down` |
| **QR-10** The new row, and the run that came from Quick Run, survive a restart. | W | `session_smoke::step_restart` |
| **QR-11** A Quick Run cannot reach outside the base folder (no `..`, no look-alike sibling). | W CLI | `test_ryos::TestIsInside`, `test_ryos::TestResolve::test_traversal_attempt_rejected` |
| **QR-12** The file index is built in the background, once at a time, served stale while it rebuilds, cached on disk, capped and filtered by extension. | W | `test_ryos::TestQuickRunIndexController`, `test_ryos::TestQuickRunIndexTTL`, `test_ryos::TestQuickRunIndexHelpers` |
| **QR-13** "Suggest as you type" off, and the extension and file-count options, change what the bar offers. | W | `qt_smoke::check_options_form` (round-trip of the values only). The bar's reaction: **untested** |

## 6. Pipelines

| Behaviour | Surfaces | Guarded by |
| --- | --- | --- |
| **PL-01** + Pipeline (header, File menu) asks for a group when on All, makes the pipeline and opens its editor; an empty name is refused. | W A · P | `qt_smoke::check_run_with_params_and_new_pipeline`, `qt_smoke::check_pipeline_editor` |
| **PL-02** The editor adds, removes and reorders steps; the first step cannot move up or start with the previous one; the list matches the stored steps. | W · P | `test_ryos::TestPipelineStepRows`, `test_ryos::TestPipelineEditorRules`, `qt_smoke::check_pipeline_editor`, `test_ryos::TestScriptDBPipelines::test_reorder_normalizes_promoted_first_step` |
| **PL-03** "With Prev" starts a step together with the one above; such steps show as parallel in the list, rows, popup and cards. | W N C D · P | `qt_smoke::check_pipeline_editor`, `test_ryos::TestPipelineStepRows::test_a_concurrent_step_is_marked_and_stays_aligned`, `test_ryos::TestRowSteps` |
| **PL-04** Each step has its own failure policy (stop / keep going), retries, run condition (always / only if nothing failed / only if something failed) and preset; the list says them in words and they persist. | W · P | `test_ryos::TestStepPolicyStorage`, `test_ryos::TestPolicyMarks`, `test_ryos::TestStepPolicyReaders`, `qt_smoke::check_pipeline_editor`, `session_smoke::step_pipeline` |
| **PL-05** Steps run in order and the output shows each step starting and how it ended, then the pipeline's result. | N C F D CLI MCP · P | `test_headless::TestRunningAPipeline::test_steps_run_in_order`, `test_ryos::TestJobController`, `session_smoke::step_pipeline` |
| **PL-06** A failed step stops the pipeline unless told to keep going; a retry runs only the failing step, up to its bound; an "only if something failed" clean-up step runs after a failure, and the run still counts as failed. | N C F D CLI MCP · P | `test_ryos::TestPipelineFailurePolicy`, `test_ryos::TestShouldRunStep`, `test_headless::TestRunningAPipeline::test_a_failed_step_stops_it_unless_told_to_continue`, `test_headless::TestRunningAPipeline::test_a_retry` |
| **PL-07** A retry is announced in the output and shown on the row; a stopped step is not retried. | N C F D R · P | `test_ryos::TestStopAndLiveStatus::test_a_retry_is_announced_and_tracked`, `test_ryos::TestStopAndLiveStatus::test_a_stopped_step_is_not_retried` |
| **PL-08** Steps that run side by side each get their own state chip and prefixed, coloured lines; a step's chip filters the tab to its lines; chips keep their height in a short panel (#20). | W D · P | `test_ryos::TestJobController::test_parallel_steps_report_their_state_and_tag_their_lines`, `test_ryos::TestParallelStepOutput`, `qt_smoke::check_parallel_step_output` |
| **PL-09** A group of steps finishes only when its last member does; a tolerated failure does not poison the group; a failure launching one member does not block its siblings. | P CLI MCP | `test_ryos::TestJobController::test_group_advances_only_after_last_member_done`, `test_ryos::TestJobController::test_group_launch_failure_does_not_block_siblings`, `test_ryos::TestPipelineFailurePolicy::test_a_tolerated_member_failure_does_not_poison_the_group` |
| **PL-10** A step that leaves a process running (a batch file with `start /b`) still finishes about a second after its own process exits; the pipeline moves on (#26). | N C F D CLI MCP · P | `test_ryos::TestRunSubprocess::test_done_comes_when_the_script_exits_with_all_its_output_first`, `test_headless::TestRunningAPipeline::test_the_batch_file_from_the_issue`, `test_headless::TestRunningAPipeline::test_a_python_step` |
| **PL-11** Stop ends such a step and the whole pipeline even when its children still hold the output pipe (#26). | R W CLI MCP · P | `test_headless::TestRunningAPipeline::test_stop_ends_a_step_whose_children_hold_the_pipe` |
| **PL-12** One undecodable byte in a script's output does not kill the run or hang the pipeline (#26). | W CLI MCP · Sc P | `test_ryos::TestRunSubprocess::test_a_byte_the_locale_cannot_decode_does_not_kill_the_run`, `test_ryos::TestDecodeOutputItem` |
| **PL-13** Output arrives line by line before the step's done item, and an unterminated last line ("Press any key...") is not lost (#26). | W CLI MCP · Sc P | `test_ryos::TestRunSubprocess::test_done_comes_when_the_script_exits_with_all_its_output_first`, `test_ryos::TestRunSubprocess::test_a_python_scripts_output_keeps_its_order` |
| **PL-14** A launcher ("don't keep in Running") run on its own leaves the Running list after the release delay and its process keeps running. | R W CLI · Sc | `qt_smoke::check_launcher_leaves_running`, `test_ryos::TestJobController::test_a_launcher_run_on_its_own_is_released`, `test_headless::TestRunningAScript::test_a_launcher_is_released` |
| **PL-15** A launcher step lets the pipeline advance when released; a late completion cannot consume another pending step; history gets one row for it. | P CLI | `test_ryos::TestLauncherStepRelease` |
| **PL-16** A launcher's output keeps reaching its tab after it is released (reads to end of file, unlike other steps). | W · Sc P | **untested** |
| **PL-17** Stop on a pipeline stops all its steps and every step process; a stopped pipeline reads "Stopped". | R N C F D CLI MCP · P | `test_headless::TestRunningAPipeline::test_stop`, `test_ryos::TestAStoppedRunIsStopped::test_a_stopped_pipeline_and_its_step`, `test_ryos::TestStopAndLiveStatus::test_terminate_tree_uses_taskkill_on_windows` |
| **PL-18** History gets a row per step plus a summary row naming the failed step; steps carry the pipeline's trigger. | W CLI MCP · P | `test_ryos::TestControllerWritesHistory::test_each_step_gets_its_own_row`, `test_ryos::TestControllerWritesHistory::test_pipeline_summary_row_on_failure_names_the_failed_step`, `session_smoke::step_pipeline` |
| **PL-19** An empty pipeline is refused with a notice, not an error. | W CLI · P | `test_ryos::TestLaunchPlanning::test_an_empty_pipeline_refuses_as_a_notice`, `test_headless::TestRunningAPipeline::test_an_empty_pipeline_is_refused` |
| **PL-20** A step's environment, working folder and parameter override reach its process; a step without them inherits its script's. | CLI W · P | `test_ryos::TestControllerBuildsRunSpec`, `test_ryos::TestScriptEnvStorage::test_pipeline_step_inherits_from_its_script` |
| **PL-21** A pipeline row keeps its own last-run result, not a step's; a pipeline counts as one job against the cap. | N C D S · P | `test_ryos::TestOverviewCards::test_a_pipelines_last_run_is_its_own_not_a_steps`, `test_ryos::TestLaunchPlanning::test_the_pipeline_cap_refuses_before_the_step_lookup` |
| **PL-22** The maximised Overview lists a pipeline's steps as cards, in order, with the file, last outcome and what differs from default. | D · P | `test_ryos::TestOverviewCards::test_a_step_card_says_what_runs_and_only_what_differs`, `qt_smoke::check_maximised_layout` |
| **PL-23** Deleting a script a pipeline uses removes those steps and the delete question names the pipeline. | N C F D · Sc P | `test_ryos::TestDeletesLeaveNothingBehind`, `session_smoke::step_favourite_and_delete` |
| **PL-24** A pipeline can be scheduled, including one in no group. | W · P | `qt_smoke::check_schedules` |
| **PL-25** A pipeline's tray line reads "Step 2/3: name". | T · P | `qt_smoke::check_tray_and_close` |
| **PL-26** The CLI runs a pipeline and reports a pass and a failure. | CLI · P | `test_cli::TestPipeline::test_a_pass_and_a_failure` |

## 7. Running and the output panel

| Behaviour | Surfaces | Guarded by |
| --- | --- | --- |
| **OP-01** A started run appears in the Running list with its start time, elapsed time and Stop; it leaves the list when it ends and its row stops saying Running. | R N C F D · Sc P | `qt_smoke::check_running_section`, `session_smoke::step_stop`, `test_ryos::TestFormatElapsed` |
| **OP-02** Several runs can go at once, up to the parallel-job cap; past it a notice ("Too many jobs") says so and nothing is started; 0 means no cap. | W S CLI · Sc P | `qt_smoke::check_jobs_run`, `test_ryos::TestLaunchPlanning::test_the_job_cap_refuses_as_a_notice_not_an_error`, `test_ryos::TestLaunchPlanning::test_zero_max_jobs_means_no_cap`, `test_ryos::TestSplitByCapacity` |
| **OP-03** The same script cannot be started twice at once from the command line or by an agent. | CLI MCP | `test_headless::TestRunningAScript::test_the_same_script_twice_is_refused`, `test_agenttools::TestRunning::test_not_twice_at_once` |
| **OP-04** A script whose file is missing is refused with a message. | W CLI | `test_ryos::TestLaunchPlanning::test_a_missing_file_is_an_error`, `test_headless::TestRunningAScript::test_a_missing_file_is_refused` |
| **OP-05** Heavy output never freezes the window: one drain stops after its time budget and coalesces a run's consecutive lines, so a chatty pipeline cannot hold the window (#29a). | W D N · Sc P | `test_ryos::TestPumpBudget`, `test_ryos::TestSplitOutputLines`, `qt_smoke::check_heavy_output_stays_responsive` (D only) |
| **OP-06** The command line and MCP drain everything, in order, with the done item delivered once and last. | CLI MCP | `test_ryos::TestPumpBudget::test_without_a_budget_a_pump_drains_everything`, `test_ryos::TestPumpBudget::test_budgeted_pumps_deliver_every_line_in_order_then_the_done_once`, `test_headless::TestRunOutput` |
| **OP-07** The output panel starts folded; Show output opens it with its find bar; Hide output folds it. | W | `qt_smoke::check_output_panel` |
| **OP-08** A tab per run, plus All, which cannot be closed and shows everything once; a closed run's later output falls back to All. | W D | `test_ryos::TestOutputRouting`, `qt_smoke::check_shell` |
| **OP-09** Lines are coloured by stream (output, errors, RYOS's own), legibly on every theme. | W D | `qt_smoke::check_output_panel`, `test_ryos::TestQtStylesheet::test_drawn_text_reads_in_every_shipped_theme` |
| **OP-10** Errors only shows just the error lines, also while the cap trims. | W D | `test_ryos::TestOutputPanelRules::test_errors_only_keeps_stderr`, `qt_smoke::check_output_panel` |
| **OP-11** Find shows a match count, Enter / Shift+Enter step through matches, matches are highlighted, a search is kept per tab, Esc clears it. | W D | `qt_smoke::check_output_panel`, `test_ryos::TestFindSpans`, `test_ryos::TestStepMatch` |
| **OP-12** Clear empties the tab; Close all closes finished tabs but keeps All and running ones; the tab menu offers Copy, Save and Close. | W | `test_ryos::TestOutputPanelRules::test_close_all_keeps_all_and_running`, `test_ryos::TestOutputPanelRules::test_tab_menu`, `qt_smoke::check_output_panel` |
| **OP-13** The buffer is trimmed to the cap by the excess only; a cap of 0 or less means no limit. | W | `test_ryos::TestOutputRouting::test_the_overflow_is_the_excess`, `test_ryos::TestOutputRouting::test_a_zero_cap_means_no_limit_not_keep_nothing`, `qt_smoke::check_shell` |
| **OP-14** Option "Open the output panel on run" opens the panel for a new run. | W | `qt_smoke::check_output_panel` |
| **OP-15** Option "Clear output between runs" empties the All output tab as each run starts (by hand, on a schedule, a pipeline, or Retry on a failed run alike; a step retried inside a pipeline is not a new run); each run's own tab, finished or still running, is kept. Option "Scroll to the newest output" scrolls. | W D · Sc P | `test_ryos::TestOutputRouting::test_clearing_between_runs_empties_all`, `::test_with_the_option_off_nothing_is_cleared`, `::test_a_run_going_in_another_tab_is_not_wiped`, `session_smoke::step_output_options` (N C), `qt_smoke::check_output_panel` (N), `qt_smoke::check_maximised_layout` (D) |
| **OP-16** In the maximised layout the output panel lives in the pane's Output tab; running the item you are looking at switches there, running another item does not. | D | `test_ryos::TestMaximisedLayout::test_the_output_tab_opens_for_the_chosen_items_run_only`, `qt_smoke::check_maximised_layout` |
| **OP-17** The window can be as narrow as its minimum and still lay out header, search, output and status bars. | W | `qt_smoke::check_output_panel` |
| **OP-18** The status bar's last line says what happened ("Ready", "Done", "Failed", "Stopped"). | W R | `session_smoke::step_status_line` ("Started N": see SM-07) |
| **OP-19** A script waiting for input does not hang its run. | CLI W | `test_ryos::TestStopAndLiveStatus::test_a_script_waiting_for_input_does_not_hang` |
| **OP-20** A finished run sends a notification unless the option is off or toasts are blocked. | W | `qt_smoke::check_updates_and_notify`, `test_ryos::TestToastsCanBeBlocked` |
| **OP-21** A run's output tab opens right after All, so the newest run is first and in view; the tab you are reading stays chosen; a re-run gets its own new tab in front, the earlier one moves right (#31). | W D · Sc P | `test_ryos::TestOutputTabOrder`, `qt_smoke::check_output_panel`, `session_smoke::step_run_and_output` (N C) |

## 8. Run history

| Behaviour | Surfaces | Guarded by |
| --- | --- | --- |
| **HI-01** Every run is recorded with status, exit code (zero shown, not blank), duration and start; failures record the script's own code. | W CLI MCP · Sc P | `test_ryos::TestRunHistoryStorage`, `test_ryos::TestControllerWritesHistory`, `qt_smoke::check_jobs_run`, `session_smoke::step_run_and_output` |
| **HI-02** History says who started a run (You, Schedule, CLI, Agent). | W CLI MCP | `test_ryos::TestRunHistoryFormatting::test_who_started_it`, `test_headless::TestRunningAScript::test_history_says_who_started_it`, `qt_smoke::check_schedules` |
| **HI-03** The History dialog lists newest first with aligned columns, a summary, a step's position for pipeline rows; its default button is Close. | N C F D · Sc P | `test_ryos::TestRunHistoryFormatting`, `qt_smoke::check_small_dialogs`, `qt_smoke::check_review_fixes` |
| **HI-04** Clear history removes only this item's runs, asks first with a count, and is off when nothing is left; a dialog for no item clears nothing. | N C F D · Sc P | `test_ryos::TestRunHistoryStorage::test_clear_for_one_item_leaves_others`, `test_ryos::TestRunHistoryFormatting::test_clear_prompt_counts_and_warns`, `qt_smoke::check_small_dialogs` |
| **HI-05** Old history is pruned at start-up by the retention option; 0 or less keeps everything. | W | `test_ryos::TestRunHistoryRetention` (the rule). `session_smoke::step_restart` (the start-up call) |
| **HI-06** History survives deleting its script. | Sc P | `test_ryos::TestDeletesLeaveNothingBehind::test_run_history_is_kept` |
| **HI-07** A failing history write never breaks the run. | W CLI | `test_ryos::TestControllerWritesHistory::test_a_history_failure_does_not_break_the_run` |
| **HI-08** The maximised History tab follows the chosen item, scripts and pipelines; Recent lines open it. | D · Sc P | `qt_smoke::check_maximised_layout`, `test_ryos::TestActivityBar::test_recent_runs_stand_for_their_steps_and_say_how_they_went` |
| **HI-09** `ryos-cli history` prints, including on a Windows console. | CLI | `test_cli::TestEditRemoveExpose::test_history`, `test_cli::TestEditRemoveExpose::test_history_prints_on_a_windows_console` |

## 9. Schedules

| Behaviour | Surfaces | Guarded by |
| --- | --- | --- |
| **SC-01** The schedule dialog offers every N minutes, daily at a time, or chosen days at a time; each mode takes only its own fields; a new schedule starts at every 30 minutes and enabled. | N C F D · Sc P | `test_ryos::TestScheduleForm`, `qt_smoke::check_small_dialogs`, `qt_smoke::check_review_fixes` |
| **SC-02** The dialog previews the next runs; a bad spec previews nothing and is refused with a warning; weekly with no days is refused. | W · Sc P | `test_ryos::TestScheduleForm::test_a_good_spec_previews_the_requested_count`, `test_ryos::TestScheduleForm::test_a_bad_spec_is_refused_as_a_warning`, `qt_smoke::check_small_dialogs` |
| **SC-03** A saved schedule loads back exactly as saved; Remove schedule deletes it; a broken stored spec still opens. | W · Sc P | `test_ryos::TestScheduleForm::test_a_weekly_schedule_loads_back`, `test_ryos::TestScheduleForm::test_a_broken_spec_still_opens`, `qt_smoke::check_small_dialogs` |
| **SC-04** Saving an enabled schedule on Windows offers to start RYOS at login, unless it already does. | W | `test_ryos::TestScheduleForm::test_login_is_offered_for_an_enabled_schedule_on_windows`, `qt_smoke::check_small_dialogs` |
| **SC-05** A due schedule fires once and moves its next run on; it does not fire twice for one due time. | W · Sc P | `test_ryos::TestScheduleRunner::test_fires_once_and_advances`, `qt_smoke::check_schedules`, `session_smoke::step_schedule` |
| **SC-06** A schedule never stacks a second run on one that is still going, skips at the job cap but still advances, and a refused run says so without disabling the schedule. | W · Sc P | `test_ryos::TestScheduleRunner::test_never_stacks_on_a_running_target`, `test_ryos::TestScheduleRunner::test_skips_at_capacity_but_still_advances`, `qt_smoke::check_schedules` |
| **SC-07** A schedule whose script is gone, or whose spec is unusable, is disabled, not retried forever. | W · Sc P | `test_ryos::TestScheduleRunner::test_missing_target_disables`, `test_ryos::TestScheduleRunner::test_unusable_spec_disables_without_launching`, `qt_smoke::check_schedules` |
| **SC-08** Time missed while RYOS was closed: run once, skip them, or run every missed one (capped); a clock jump back does not rewind. | W | `test_ryos::TestResolveDue` |
| **SC-09** Next-run arithmetic keeps wall-clock time across daylight-saving changes, month, year and leap-day rollovers. | W | `test_ryos::TestNextOccurrence`, `test_ryos::TestDaylightSaving`, `test_ryos::TestNormalizeSpec` |
| **SC-10** A scheduled row shows a SCHEDULED badge (full rows). | N · Sc P | `test_ryos::TestFileDropAndCardDetails::test_badges`, `qt_smoke::check_badges_banner_previews` |
| **SC-11** A scheduled run is recorded as a schedule run. | W | `qt_smoke::check_schedules` |
| **SC-12** Deleting an item deletes its schedule. | Sc P | `test_ryos::TestDeletesLeaveNothingBehind::test_delete_takes_steps_presets_and_schedule`, `test_ryos::TestDeletesLeaveNothingBehind::test_delete_pipeline_takes_its_schedule` |
| **SC-13** Up next lists the soonest scheduled runs first, only what will run, with when and how often; the status bar repeats the gist. | D R | `test_ryos::TestActivityBar::test_up_next_soonest_first_and_only_what_will_run`, `qt_smoke::check_maximised_layout` |
| **SC-14** The Schedule... button in the maximised pane opens the schedule dialog for the chosen item. | D · Sc P | **untested** |

## 10. Window, tray and start-up

| Behaviour | Surfaces | Guarded by |
| --- | --- | --- |
| **TW-01** Closing with the tray on hides to the tray (with a first-time prompt and a "don't ask" box); with it off, closing quits; Cancel on the prompt does nothing. | W T | `test_ryos::TestTrayPolicy`, `qt_smoke::check_tray_and_close` |
| **TW-02** Hiding to the tray does not stop running jobs. | W T | `qt_smoke::check_tray_and_close` |
| **TW-03** The tray menu lists running jobs, then Show and Exit; long labels are clamped; the tooltip names one job or counts several and drops finished ones. | T | `test_ryos::TestTrayTitle`, `test_ryos::TestTrayMenuLabels`, `test_ryos::TestTrayPolicy::test_menu_lists_jobs_then_show_and_exit`, `qt_smoke::check_tray_and_close` |
| **TW-04** Picking a job in the tray menu shows its output. | T W | `qt_smoke::check_tray_and_close` |
| **TW-05** Quitting asks if jobs are running; confirming stops them, removes the tray icon and releases the single-instance socket. | W T | `qt_smoke::check_tray_and_close`, `test_ryos::TestTrayPolicy::test_quit_prompt_and_verbs` |
| **TW-06** A second launch restores the running window instead of opening another; messages are whole, tokens are checked. | W | `test_ryos::TestSignalExisting`, `test_ryos::TestInstanceListener`, `qt_smoke::check_tray_and_close` |
| **TW-07** Minimise to tray vs stay on the taskbar follows its option (#21). | W T | `test_ryos::TestTrayPolicy::test_minimize_and_start`, `test_ryos::TestTrayPolicy::test_minimising_can_stay_on_the_taskbar`, `qt_smoke::check_tray_round_trip` |
| **TW-08** A window hidden to the tray comes back as it went (maximised if it was) and in place on a relaunch (#22). | W D T | `test_ryos::TestTrayPolicy::test_the_window_comes_back_as_it_went`, `qt_smoke::check_tray_round_trip` |
| **TW-09** The window opens where it was, or on the cursor's monitor, or snapped to a corner; never off the work area, also with mixed-DPI monitors. | W | `test_ryos::TestWindowPlacement`, `test_ryos::TestClampToWorkArea`, `test_ryos::TestRelocateGeometry`, `qt_smoke::check_window_placement`, `qt_smoke::check_mixed_dpi_placement` |
| **TW-10** Keep on top applies at start and when Options are applied. | W | `qt_smoke::check_window_placement` |
| **TW-11** The window opens with focus in the search box; Tab moves between header, list and output. | W | `qt_smoke::check_focus_starts_in_search` |
| **TW-12** Search filters rows as you type and shows "N of M"; an empty result says so and hides empty sections; a reload keeps the filter; clearing restores everything. | W N C A | `test_ryos::TestSearchNormalizeAndMatch`, `test_ryos::TestSearchEmptyState`, `qt_smoke::check_shell`, `qt_smoke::check_search_empty_state`, `session_smoke::step_quick_run_search_select` |
| **TW-13** When the open group has no match, the hint links to other groups that do. | W | `test_ryos::TestComputeHint` (the rule). The links in the window: **untested** |
| **TW-14** Esc clears the search box; Down goes to the first row. | W | `qt_smoke::check_keyboard_through_the_list` (Down), `session_smoke::step_keyboard_and_menu` (Esc) |
| **TW-15** The menus are File (New script / pipeline / group, Import, Export, Exit), Options (Options, Appearance, Start with Windows, Select, Delete All) and Help (Check for updates, Suggest a feature, Report a bug, Open log folder). | W | `session_smoke::step_groups_and_scripts` (File menu), `qt_smoke::check_bug_report` (Help menu), `session_smoke::step_help_and_log`, plus `qt_smoke::check_suggestion` (Help menu) |
| **TW-16** Start with Windows turns the run-at-login entry on and off. | W | **untested** |
| **TW-17** A newer release shows the update banner (fetched off the UI thread, once, dismissible, naming this download's zip); a manual check always answers; an automatic check that fails says nothing. A release candidate sees its final release as newer; a pre-release is never offered (`/releases/latest` skips it). | W CLI | `test_ryos::TestUpdateStatus`, `test_ryos::TestParseVersion`, `test_ryos::TestUpdateStatus::test_a_release_candidate_sees_its_final_as_newer`, `qt_smoke::check_updates_and_notify` |
| **TW-18** Report a bug (status bar button and Help menu) opens a new GitHub issue filled in with versions (a build's commit too), theme and layout, and sends nothing; then shows the log's path with an Open log folder button and warns it can hold script paths and output (#29). | W | `test_ryos::TestBugReport`, `test_ryos::TestBuildInfo::test_the_bug_report_names_the_commit`, `test_ryos::TestSuggestion::test_the_bug_report_link_is_unchanged`, `qt_smoke::check_bug_report`, `session_smoke::step_help_and_log` |
| **TW-19** A database a newer RYOS reshaped makes the window say so in the window and the log, and stop, leaving the file untouched. | W CLI | `test_ryos::TestCompatibleFrom`, `qt_smoke::check_newer_database_is_refused`, `release_check::newer_database_refused` |
| **TW-20** Maximising shows the rail, group picker, detail pane and Activity bar and turns rows compact; restoring brings back the pills, the output panel and full rows; the option turns the layout off. | D | `test_ryos::TestMaximisedLayout`, `qt_smoke::check_maximised_layout` |
| **TW-21** The rail's Search puts the keyboard in the search box; the group picker offers groups, All and New group; Activity shows or hides the bar and the choice is remembered. | D | `qt_smoke::check_maximised_layout` |
| **TW-22** The Overview shows a script's presets as pills (the highlighted one is what Run passes, each pill's play runs with it), then facts and a Last run box with Open output or History. | D · Sc | `test_ryos::TestMaximisedLayout`, `test_ryos::TestOverviewCards::test_the_last_run_box`, `qt_smoke::check_maximised_layout` |
| **TW-23** The Activity bar shows running now (with Stop), up next and recent runs; a pipeline stands for its steps; the rail shows how many are running. | D R | `test_ryos::TestActivityBar`, `qt_smoke::check_maximised_layout` |
| **TW-24** The Activity bar and the pane say "Today" / "Tomorrow" / the weekday correctly. | D | `test_ryos::TestActivityBar::test_day_words` |
| **TW-25** Help → Open log folder opens the folder RYOS's logs are in, in two clicks (#29). | W | `qt_smoke::check_bug_report`, `session_smoke::step_help_and_log` |
| **TW-26** Suggest a feature (a status-bar button just left of the bug button, and Help → Suggest a feature just above Report a bug; normal, compact and maximised; every Windows download, with or without AI agents) opens a new GitHub issue titled "Suggestion: " and labelled enhancement. The issue asks what RYOS should do, what the person is trying to get done and how they do it today, and anything else; its footer holds only the RYOS version and download. RYOS sends nothing and shows no dialog; the status bar says "Opened a suggestion in your browser — nothing is sent until you submit it." | W D R | `test_ryos::TestSuggestion`, `qt_smoke::check_suggestion`, `qt_smoke::check_maximised_layout`, `session_smoke::step_help_and_log` |
| **TW-27** Both `RYOS.exe` and `ryos-cli.exe` carry the publisher (company Zenitus (Lê Quang Vũ), copyright © 2026 Lê Quang Vũ (Zenitus)) in Properties → Details. | W CLI | `test_ryos::TestBuildInfo::test_the_publisher` |

## 11. Command line

| Behaviour | Surfaces | Guarded by |
| --- | --- | --- |
| **CLI-01** `ryos` alone opens the window; `--version` and `--help` work; a bad command line is refused. | CLI | `test_cli::TestWhichCommandLines` |
| **CLI-02** `list` shows scripts and pipelines with their full names and ids, without their environment, and says what agents may run; `--json` too. `list --group G` shows only that group and names what is not available to agents yet; an unknown group is refused (125) naming the groups. | CLI · Sc P | `test_cli::TestList`, `test_cli::TestEditRemoveExpose::test_list_says_what_agents_may_run`, `test_cli::TestList::test_one_group`, `test_cli::TestList::test_an_unknown_group` |
| **CLI-03** A script is named by name, `group/name` or `#id`; an ambiguous name is refused listing the candidates; no match is refused. | CLI · Sc P | `test_headless::TestResolve` |
| **CLI-04** `run` streams output, exits with the script's code (1 when it has none, 124 timed out, 125 refused), `--json` prints one result, `--params` and `--preset` choose the parameters. | CLI · Sc | `test_cli::TestRun`, `test_headless::TestRunningAScript` |
| **CLI-05** Ctrl+C stops the run first and exits 130. | CLI | **untested** |
| **CLI-06** A timeout stops the run and exits 124. | CLI | `test_cli::TestRun::test_a_timeout`, `test_headless::TestRunningAScript::test_a_timeout_stops_it` |
| **CLI-07** Parameters and presets: own parameters by default, a preset by label, or `--params`; an unknown preset is refused. | CLI · Sc | `test_cli::TestRun::test_params`, `test_cli::TestRun::test_refusals`, `test_headless::TestRunningAScript::test_parameters_and_presets` |
| **CLI-08** `pipeline` runs every step and exits as the run did. | CLI · P | `test_cli::TestPipeline`, `test_headless::TestRunningAPipeline` |
| **CLI-09** `add` creates a script as the dialog would, making the group, refusing a duplicate name, a missing working folder or a question unless `--yes`; making it available to agents needs a person. | CLI · Sc | `test_cli::TestAdd` |
| **CLI-10** `edit` changes only what was given; `remove` asks and names its pipelines; `expose` turns agent access on and off; `preset` adds and removes. | CLI · Sc P | `test_cli::TestEditRemoveExpose`, `release_check::cli_management` |
| **CLI-11** The command line takes no instance lock, writes no run-at-login entry and imports no Qt. | CLI | `test_cli::TestTheRealEntryPoint` |
| **CLI-12** A command-line run reaches a running window's row (a failed run turns it to Retry) and a script added from the command line appears, without bringing the window forward. | CLI W | `qt_smoke::check_cli_run_reaches_the_window` |
| **CLI-13** `--version` says which download this is and, in a build, the commit it was built from; `version --check` names its zip. | CLI | `test_cli::TestVersion`, `test_cli::TestVersion::test_names_the_build_commit`, `test_ryos::TestBuildInfo`, `test_ryos::TestBuildInfo::test_a_build_names_its_commit` |
| **CLI-14** A newer database is refused with 125. | CLI | `test_ryos::TestCompatibleFrom::test_the_cli_refuses_with_125`, `release_check::newer_database_refused` |
| **CLI-15** A run's output is kept in a bounded buffer, lines split across chunks, with old lines dropped and paging skipping them. | CLI MCP | `test_headless::TestRunOutput` |
| **CLI-16** A run from the command line is recorded in History as `cli` and a stop ends it. | CLI · Sc P | `test_headless::TestRunningAScript::test_history_says_who_started_it`, `test_headless::TestRunningAScript::test_stop` |
| **CLI-17** `ryos-cli version` prints where the logs are: the folder and each log this download writes (#29). | CLI | `test_cli::TestVersion::test_says_where_the_logs_are`, `test_ryos::TestBugReport::test_log_lines_per_download` |
| **CLI-18** `expose --group G on` lists only what it would change and asks once (a terminal or `--yes`); with nothing new it says so and exits 0; run again, it asks only about what was added since; `off` turns them all off without asking; a script moved into the group later is not made available; an unknown group is refused (125) naming the groups; an empty group says so. | CLI · Sc P | `test_cli::TestExposeAGroup`, `test_ryos::TestGroupExposure` |

## 12. MCP (AI agents)

| Behaviour | Surfaces | Guarded by |
| --- | --- | --- |
| **MCP-01** An agent sees only what is ticked "Available to agents"; anything else is "not found", never named; unticking takes effect at once; an unavailable twin does not make a name ambiguous. | MCP · Sc P | `test_agenttools::TestOnlyWhatWasMadeAvailable` |
| **MCP-02** Nothing is available until a person says so: the migration, an import, a clone or a copy never turn it on, nor does moving a script into a group that was exposed. | MCP W CLI · Sc P | `test_ryos::TestAgentExposure`, `test_cli::TestExposeAGroup::test_moving_in_later_grants_nothing` |
| **MCP-03** An agent runs a script with its own parameters or a preset by label, never free text. | MCP · Sc | `test_agenttools::TestRunning::test_presets_by_label_and_nothing_else` |
| **MCP-04** A run reports its output and outcome; a failure, a stop and a pipeline run work; a second run of the same item is refused; an unknown run id is named. | MCP · Sc P | `test_agenttools::TestRunning` |
| **MCP-05** Output comes a page at a time with long lines capped; waiting returns as soon as there is news. | MCP | `test_agenttools::TestOutputInPages` |
| **MCP-06** A finished agent run tells a running window to refresh its rows. | MCP W | `test_agenttools::TestRunning::test_a_running_window_is_told` |
| **MCP-07** The real server lists six tools, serves only available items, runs one by preset and refuses an unavailable one with a readable message. | MCP | `test_mcpserver::TestMcpServer::test_the_tools`, `release_check::mcp_windows_ai`, `release_check::mcp_agent` (the built servers: list, run, poll, stop) |
| **MCP-08** The Windows download has no MCP server: `ryos-cli mcp` exits 125 saying which download has it; without the SDK it says how to get it. | MCP CLI | `test_cli::TestMcpInTheBuildWithoutIt`, `test_cli::TestMcpWithoutTheSdk`, `test_ryos::TestBuildInfo::test_which_builds_carry_mcp_and_offer_agents`, `release_check::mcp_windows` |
| **MCP-09** The "Available to agents" box is in the script dialog and the pipeline editor, off until ticked, hidden in the build without agents but its stored value untouched; so are the group menu's and select mode's agent actions. | W · Sc P | `qt_smoke::check_script_dialog`, `qt_smoke::check_pipeline_editor`, `test_ryos::TestScriptFormLoadSave::test_agents_off_unless_ticked_and_untickable`, `test_ryos::TestCardMenu::test_group_menu_offers_agents_only_where_offered`, `session_smoke::step_agents_for_a_group` |
| **MCP-10** The command line shows which items agents may run, and exposing from it, one item or a whole group, needs a person to confirm. | CLI | `test_cli::TestEditRemoveExpose::test_expose_on_and_off`, `test_cli::TestAdd::test_expose_needs_a_person`, `test_cli::TestExposeAGroup::test_refused_without_a_terminal_or_yes` |

## 13. Parameters, presets and how a script runs

| Behaviour | Surfaces | Guarded by |
| --- | --- | --- |
| **PR-01** Saved parameters are passed on every run, quoted values stay one value, and parsing follows the platform's rules. | N C F D CLI · Sc | `test_ryos::TestBuildCommand`, `test_ryos::TestParseInput` |
| **PR-02** A script with presets shows a drop-down with its own parameters first; "(no parameters)" passes none; Run passes the choice. | N C F · Sc | `qt_smoke::check_run_with_params_and_new_pipeline`, `test_ryos::TestRunParams`, `test_ryos::TestParamOptions` |
| **PR-03** "Ask for a temporary parameter on each run" asks every time; what is typed is appended once and not kept; cancelling runs nothing; an empty answer is allowed. | N C F D · Sc | `qt_smoke::check_run_with_params_and_new_pipeline`, `qt_smoke::check_small_dialogs`, `test_ryos::TestRunParams::test_temp_param_is_appended_once` |
| **PR-04** The play-with-plus button (and "Run with parameters...") runs with what was typed, keeps it as the script's parameters and adds a preset, once. | N C F D · Sc | `qt_smoke::check_run_with_params_and_new_pipeline`, `test_ryos::TestRunParams::test_remember_run_params` |
| **PR-05** Presets are added, used, edited and removed in the script dialog and keep their order; each script has its own. | W · Sc | `qt_smoke::check_script_dialog`, `test_ryos::TestParamPresets` |
| **PR-06** The script dialog: name required; a path needed unless an interpreter is given; a missing file asks rather than refusing; a path outside the base folder asks; relative paths join the base folder and cannot escape it. | W · Sc | `test_ryos::TestScriptFormValidation`, `test_ryos::TestVerdict`, `qt_smoke::check_script_dialog` |
| **PR-07** A new script defaults to the group on screen; with no groups, Add Script makes one. | W | `qt_smoke::check_script_dialog` |
| **PR-08** The script dialog's Cancel writes nothing, Delete asks, and reopening shows exactly what was saved. | W · Sc | `qt_smoke::check_script_dialog`, `test_ryos::TestScriptFormLoadSave` |
| **PR-09** The interpreter is detected from the extension when blank; a stored one wins; RYOS's own exe is never used as one. | N C F D CLI MCP · Sc | `test_ryos::TestDetectInterpreter`, `test_ryos::TestResolveInterpreter` |
| **PR-10** The environment (`KEY=value` lines) and working folder reach the process; the working folder defaults to the script's own folder. | N C F D CLI MCP · Sc P | `test_ryos::TestRunSpecReachesTheProcess`, `test_ryos::TestBuildRunSpec`, `test_ryos::TestWorkingDirFor`, `test_ryos::TestParseEnvText`, `session_smoke::step_run_and_output` |
| **PR-11** The Launcher flag is stored and survives clone, copy, export and edit. | W · Sc | `qt_smoke::check_script_dialog`, `test_ryos::TestScriptDBDetached`, `test_ryos::TestExportImportFidelity::test_detached_survives` |

## 14. Import and export

| Behaviour | Surfaces | Guarded by |
| --- | --- | --- |
| **IE-01** Export all groups and Export group write a file and say its name (not just its folder). | W | `test_ryos::TestConfigIO::test_export_names`, `test_ryos::TestConfigIO::test_export_status_names_the_file_not_the_folder`, `qt_smoke::check_group_management`, `qt_smoke::check_context_menus` |
| **IE-02** A round trip keeps scripts, flags, presets, pipelines, step order, policies and parameter overrides, colours, favourites and environment. | Sc P | `test_ryos::TestExportImportFidelity`, `test_ryos::TestExportImportPipelines`, `test_ryos::TestScriptDBExportImport` |
| **IE-03** Older (v3) files still import with defaults; unknown values fall back; hostile values are clamped; a step whose script is missing is skipped, not fatal. | Sc P | `test_ryos::TestExportImportFidelity::test_v3_file_still_imports`, `test_ryos::TestExportImportFidelity::test_step_with_missing_script_is_skipped_not_fatal`, `test_ryos::TestStepPolicyStorage::test_import_clamps_hostile_values` |
| **IE-04** Import asks Merge / Replace / Cancel; Merge skips what is already there and never overwrites; Cancel imports nothing. | W · Sc P | `test_ryos::TestConfigIO::test_import_asks_with_named_choices`, `test_ryos::TestScriptDBExportImport::test_import_merge_skips_duplicates`, `qt_smoke::check_review_fixes`, `qt_smoke::check_group_management` |
| **IE-05** Replace swaps the groups' scripts and pipelines and leaves other groups alone. | W · Sc P | `test_ryos::TestScriptDBExportImport::test_import_replace_clears_existing`. Through the window: **untested** |
| **IE-06** Importing the same file twice adds nothing; imported groups appear as tabs and the status line counts what was added. | W | `qt_smoke::check_group_management`, `session_smoke::step_export_import` |
| **IE-07** An import never makes anything available to agents. | W MCP | `test_ryos::TestAgentExposure::test_an_import_never_grants_it` |
| **IE-08** Delete All counts scripts, pipelines and groups from the database; with nothing it does not ask; confirming leaves nothing behind (pipelines too). | W | `test_ryos::TestConfigIO::test_delete_all_counts_what_it_deletes`, `test_ryos::TestDeletePromptsNamePipelines`, `qt_smoke::check_group_management` |

## 15. Settings and themes

| Behaviour | Surfaces | Guarded by |
| --- | --- | --- |
| **ST-01** The Options dialog is generated from the settings schema: every setting has a control on its tab, opening and saving changes nothing, entries are coerced into bounds and never raise. | W | `test_ryos::TestSettingsSchema`, `qt_smoke::check_options_form` |
| **ST-02** A missing or corrupt settings file gives defaults; unknown keys are kept; values round-trip. | W | `test_ryos::TestSettings` |
| **ST-03** Saving Options writes `settings.json` and applies live; they survive a restart. | W | `session_smoke::step_options_and_theme`, `session_smoke::step_restart`, `qt_smoke::check_window_placement` |
| **ST-04** Turning compact cards on rebuilds the list. | N C | `qt_smoke::check_window_placement` |
| **ST-05** The maximised-layout option, the hover-preview option and the card size take effect. | D C N | `qt_smoke::check_maximised_layout`, `qt_smoke::check_badges_banner_previews`, `qt_smoke::check_cards` |
| **ST-06** Every shipped theme has a complete palette, meets contrast, generates a stylesheet and actually paints the window and output panel. | W | `test_ryos::TestThemeEngine`, `test_ryos::TestQtStylesheet`, `qt_smoke::check_every_theme_generates`, `qt_smoke::check_stylesheet_reaches_real_widgets` |
| **ST-07** A palette missing a key raises instead of producing CSS with holes. | W | `qt_smoke::check_a_short_palette_is_refused`, `test_ryos::TestQtStylesheet::test_a_missing_key_raises_rather_than_emitting_a_hole` |
| **ST-08** Re-theming repaints the window live. | W | `qt_smoke::check_shell`, `session_smoke::step_options_and_theme` |
| **ST-09** Appearance: picking a theme previews it live and saves nothing until Save; Cancel restores; the accent previews and can be reset. | W | `qt_smoke::check_theme_editor_and_appearance` |
| **ST-10** Custom themes can be created, edited, renamed, deleted, imported and exported; a name that clashes (any case) or an unreadable colour pair is refused or warned. | W | `qt_smoke::check_theme_editor_and_appearance`, `test_ryos::TestCustomThemes`, `test_ryos::TestThemeFormRules`, `test_ryos::TestUserThemeFolder` |
| **ST-11** The bundled and gallery themes load and import. | W | `test_ryos::TestBundledThemes`, `test_ryos::TestThemeGallery`, `test_ryos::TestBaseThemes` |
| **ST-12** The chosen theme survives a restart. | W | `session_smoke::step_restart` |
| **ST-13** The "Write a log file" and "Log script output too" options. | W | **untested** |

## 16. Data and storage

| Behaviour | Surfaces | Guarded by |
| --- | --- | --- |
| **DB-01** A new database is stamped current; migrations run in order, once, and are safe to run twice; an old schema upgrades; a database from every past release upgrades with nothing lost. | W CLI MCP | `test_ryos::TestSchemaVersioning`, `test_ryos::TestRunMigrations`, `test_ryos::TestScriptDBMigration`, `test_ryos::TestFixtureUpgrades`, `release_check::fixture_upgrade_<name>` (one per `tests/fixtures/db/*.db`) |
| **DB-02** Accessor rows keep their pinned widths; the UI slices instead of unpacking a fixed number of names. | N C F D | `test_ryos::TestRowWidthsArePinned`, `test_ryos::TestPipelineEditorUnpacksDefensively` |
| **DB-03** Groups, scripts and pipelines keep their order; swap and move-to-top are reversible; reordering and moving between groups work for both kinds. | Sc P | `test_ryos::TestScriptDBOrdering`, `test_ryos::TestScriptDBReorderMove` |
| **DB-04** Deleting a group orphans its items into Ungrouped; renaming a group renames it for scripts and pipelines. | W | `test_ryos::TestScriptDBGroups::test_delete_group_orphans_scripts_and_pipelines`, `test_ryos::TestScriptDBGroups::test_rename_group_propagates_to_scripts_and_pipelines` |
| **DB-05** Rows that point at deleted scripts are cleaned up when the database opens. | W | `test_ryos::TestOrphanMigration` |
| **DB-06** Colours (highlight) are stored per script and pipeline and do not disturb earlier columns. | N C F D · Sc P | `test_ryos::TestLabelColorDB` |
| **DB-07** Moving between downloads (RYOS Agent, Windows with or without agents) keeps scripts, history, presets and agent exposure, in either order. | W CLI MCP | `release_check::mixed_agent_first`, `release_check::mixed_app_first` |

## Escapes

Every bug found after a release gets one line here, in the fix's commit, and that
commit adds the check named: "#NN (vX.Y.Z): should have been caught by <check>;
added <test / map entry / release_check case>".

- #26 (v2.3.0): a pipeline stalled after a step that left a process running; should have been caught by a pipeline test with a step whose children outlive it; added PL-10 to PL-13 and their `test_headless::TestRunningAPipeline` tests.
- #27 (v2.3.0): select mode did not tick pipelines, and a click on a row did not tick it; should have been caught by a select-mode check covering pipelines; added SM-01, SM-02, SM-06, GR-31 and `test_ryos::TestSelectionTakesPipelines`.
- #29a (v2.3.0): a chatty pipeline froze the window; should have been caught by a heavy-output check in the window; added OP-05 and `qt_smoke::check_heavy_output_stays_responsive`.
- #29b (v2.3.0): the log was hard to find when something went wrong; should have been caught by a user using the build before it shipped (the release candidate phase); added TW-18, TW-25, CLI-17 and `session_smoke::step_help_and_log`.
- #30 (v2.3.0, since the Qt port in v2.0.0): a Quick Run of a new file did not show its row; should have been caught by a Quick Run check in every layout; added QR-08 and `qt_smoke::check_quick_run_shows_new_row`.
- OP-15 (v2.3.1, since the tabbed output panel in v1.3.1): "Clear output between runs" did nothing; should have been caught by a check that runs twice with the option on and reads the All tab; added `test_ryos::TestOutputRouting` (`cleared_when_run_starts`: on, off, a running tab kept), `session_smoke::step_output_options` asserting it in both layouts, and a maximised-layout check in `qt_smoke::check_maximised_layout`.

---

## Untested: backlog

Entries marked **untested** above, then the entries that are guarded on some surfaces
only. "-> session_smoke now" means it is added to `tests/session_smoke.py` as part of
step 13; "-> 2.4" is left for 2.4.

### Untested entries

| Entry | What is missing | Plan |
| --- | --- | --- |
| **GR-24** (part) Copy to leaves the schedule behind | only run history is tested | -> 2.4 (a unit test in `TestCopyBetweenGroups`) |
| **FV-13** The detail pane's star | the pane's Run / Retry are tested; its star is not | -> 2.4 |
| **SC-14** The pane's Schedule... button | not pressed in any test | -> 2.4 |
| **PL-16** A released launcher's output still reaches its tab | the release is tested; the follow-to-end-of-file rule (`follow_leftovers`) is not | -> 2.4 |
| **QR-13** "Suggest as you type" off, and the index options, change the bar | the form round-trips the values; the bar's reaction is not checked | -> 2.4 |
| **IE-05** Replace through the window | tested in the database only | -> 2.4 |
| **TW-13** (part) The hint's links to other groups | the rule is tested; the links in the window are not | -> 2.4 |
| **TW-15** (part) The Options and Help menus hold what the tutorial says | File and Help are checked; Options isn't | -> 2.4 |
| **TW-16** Start with Windows toggle | would write the registry; needs the injected startup object | -> 2.4 |
| **CLI-05** Ctrl+C exits 130 | needs a real interrupt signal | -> 2.4 |
| **ST-13** The log-file options | not tested | -> 2.4 |
| **TW-27** (part) The exe's version resource | the publisher constants are tested; the built exe's version resource is not read by any test (the release review reads it) | -> 2.4 |
| **SM-16** Starring or maximising in select mode leaves it | `_set_favorite` -> `_defer_reload` -> `load_from_db` -> `set_select_mode(False)`; `set_workspace` reloads when rows are not compact | -> 2.4: keep the mode and the ticked (kind, id) across a reload, except after Delete selected (SM-09) |
| **SM-13** (part) Run selected / Delete on C, D; a search active | not tested | -> 2.4 |

### Guarded on some surfaces only

These behaviours have a test, but it opens one layout. They are where "working on A
breaks B" has happened. The table says which surfaces are unguarded.

| Behaviour | Guarded on | Unguarded | Plan |
| --- | --- | --- | --- |
| Click Run / star on a row (RC-03, RC-09, RC-10, FV-05) | N C (a real click on Run: `session_smoke::step_run_click`, both layouts; C also for the overlap check) | F D: a click on the real button | -> 2.4 |
| Select mode (SM-01 to SM-09, SM-13, SM-14) | N; ticking, Select All and the bar's fit also C, D (`check_select_bar_fits`) | Run selected / Delete on C, D, with a search active; SM-14 on the All tab and D | -> 2.4 |
| Keyboard through the list, F2, Menu key (RC-29) | N | C, D | -> 2.4 |
| Right-click menu actions (RC-20 to RC-25) | N | C, F, D (three dots) | -> 2.4 |
| Drag and drop (GR-14, GR-15) | N | C, D list | -> 2.4 |
| Outside-folder warning when running (GR-30) | N (and compact tag) | F, D: Run from a chip or from the pane | -> 2.4 |
| Heavy output (OP-05) | D | N | -> 2.4 |
| Pane buttons (RC-35) | Run, Retry | Edit, star, three dots, Schedule | -> 2.4 |
| Newest run's tab right after All (OP-21) | N C (`qt_smoke::check_output_panel`, `session_smoke::step_run_and_output`) | D: the same bar in the detail pane | -> 2.4 |
